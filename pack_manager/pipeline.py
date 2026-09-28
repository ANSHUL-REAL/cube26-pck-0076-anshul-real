"""verify_box: photos + order in, sealed evidence record out.

Fail-open: if the vision model errors or times out, the photos and a record are still
produced, marked pending, so the operator can check by hand without losing the box.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .catalogue import select_candidates
from .config import Settings
from .decision import LOCAL_GATE_VERSION, decide
from .evidence import new_record_id, seal, utcnow
from .models import (
    AGENT_NAME,
    Catalogue,
    Check,
    Decision,
    EvidenceRecord,
    ImageRef,
    Order,
    Outcome,
    QualityReport,
    RecordStatus,
    Verdict,
)
from .quality import PreparedImage, prepare_photo
from .vision.base import Perceiver
from .vision.prompt import PROMPT_VERSION

log = logging.getLogger(__name__)


class QualityRejected(Exception):
    def __init__(self, reports: list[QualityReport]):
        self.reports = reports
        super().__init__("One or more photos failed the quality gate.")


@dataclass
class Photo:
    data: bytes
    role: str = "top_down"


def prepare_photos(photos: list[Photo], settings: Settings) -> list[PreparedImage]:
    if not photos:
        raise ValueError("At least one photo of the open box is required.")
    if len(photos) > settings.max_box_photos:
        raise ValueError(f"At most {settings.max_box_photos} photos per box.")
    return [prepare_photo(p.data, settings, p.role) for p in photos]


def cost_usd(usage: dict, settings: Settings) -> float | None:
    if settings.cost_per_1m_input_usd is None or settings.cost_per_1m_output_usd is None:
        return None
    out_tokens = usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)
    return round(
        usage.get("input_tokens", 0) / 1e6 * settings.cost_per_1m_input_usd
        + out_tokens / 1e6 * settings.cost_per_1m_output_usd,
        6,
    )


def verify_box(
    order: Order,
    prepared: list[PreparedImage],
    catalogue: Catalogue,
    perceiver: Perceiver,
    settings: Settings,
    *,
    operator_label: str,
    catalogue_root: Path | None = None,
    force_quality: bool = False,
    captured_at: datetime | None = None,
) -> EvidenceRecord:
    reports = [p.quality for p in prepared]
    if any(r.gate == "FAIL" for r in reports) and not force_quality:
        raise QualityRejected(reports)

    captured_at = captured_at or utcnow()
    candidates = select_candidates(order, catalogue, settings)
    images = [
        ImageRef(image_id=p.image_id, role=p.role, sha256=p.sha256, original_sha256=p.original_sha256,
                 mime=p.mime, width=p.width, height=p.height, quality=p.quality)
        for p in prepared
    ]
    subject = {
        "type": "outbound_box",
        "unit_id": order.unit_id,
        "order_id": order.order_id,
        "channel": order.channel,
        "expected_lines": [line.model_dump() for line in order.lines],
    }
    agent = {"name": AGENT_NAME, "version": __version__, "prompt_version": PROMPT_VERSION}

    try:
        perception = perceiver.perceive(prepared, candidates, catalogue.allowed_inserts, catalogue_root)
    except Exception as exc:  # fail open on any model failure, never lose the capture
        log.warning("Perception failed for order %s: %s", order.order_id, exc)
        checks = [
            Check(check_key="image_quality",
                  verdict=Verdict.PASS if all(r.gate == "PASS" for r in reports) else Verdict.UNCERTAIN,
                  confidence=None, detail="Local photo checks ran.", model_version=LOCAL_GATE_VERSION),
            Check(check_key="vision", verdict=Verdict.NOT_CHECKED, confidence=None,
                  detail=f"Vision model unavailable: {exc}", model_version=settings.gemini_model),
        ]
        record = EvidenceRecord(
            record_id=new_record_id(),
            organization_id=order.organization_id,
            client_id=order.client_id,
            agent=agent,
            subject=subject,
            captured_at=captured_at,
            operator_label=operator_label,
            images=images,
            observations={"error": str(exc)},
            checks=checks,
            outcome=Outcome(
                decision=Decision.PENDING, decided_by=None, decided_at=None,
                reasons=["The vision model did not answer. The photos are saved."],
                fix_instructions=["Check the box by hand against the order, then record your decision."],
            ),
            status=RecordStatus.PENDING,
        )
        return seal(record)

    result = decide(order, catalogue, perception, reports, settings)
    agent["model_version"] = perception.model_version
    agent["prompt_version"] = perception.prompt_version
    observations = {
        **result.observations,
        "usage": perception.usage,
        "cost_usd": cost_usd(perception.usage, settings),
        "cached_response": perception.cached,
    }
    record = EvidenceRecord(
        record_id=new_record_id(),
        organization_id=order.organization_id,
        client_id=order.client_id,
        agent=agent,
        subject=subject,
        captured_at=captured_at,
        operator_label=operator_label,
        images=images,
        observations=observations,
        checks=result.checks,
        outcome=Outcome(
            decision=result.decision,
            decided_by="agent",
            decided_at=utcnow(),
            reasons=result.reasons,
            fix_instructions=result.fix_instructions,
        ),
        status=RecordStatus.PENDING_REVIEW if result.decision == Decision.UNCERTAIN else RecordStatus.FINAL,
    )
    return seal(record)
