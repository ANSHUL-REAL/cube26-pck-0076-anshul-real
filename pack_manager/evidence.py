"""Evidence records: building, hashing, verifying and overriding.

content_hash is SHA-256 over the record's canonical JSON (sorted keys, no whitespace,
content_hash itself excluded). It covers the hashes of the stored photos. It makes any
edit to a record detectable when the record is compared with its hash. It is NOT an
append-only log or an externally anchored proof, and we don't claim it is.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .models import Decision, EvidenceRecord, Override, RecordStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def new_record_id() -> str:
    return "PCK-" + uuid.uuid4().hex[:12].upper()


def canonical_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(record: EvidenceRecord) -> str:
    data = record.model_dump(mode="json")
    data.pop("content_hash", None)
    return "sha256:" + hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def seal(record: EvidenceRecord) -> EvidenceRecord:
    return record.model_copy(update={"content_hash": compute_hash(record)})


def verify(record: EvidenceRecord) -> bool:
    return bool(record.content_hash) and record.content_hash == compute_hash(record)


def apply_override(
    record: EvidenceRecord,
    new_decision: Decision,
    reason_code: str,
    operator_label: str,
    note: str = "",
    at: datetime | None = None,
) -> EvidenceRecord:
    """Record a human decision. The agent's checks and the prior outcome are kept."""
    at = at or utcnow()
    entry = Override(
        original_decision=record.outcome.decision,
        new_decision=new_decision,
        reason_code=reason_code,
        note=note,
        operator_label=operator_label,
        at=at,
        prior_content_hash=record.content_hash,
    )
    outcome = record.outcome.model_copy(
        update={"decision": new_decision, "decided_by": f"operator:{operator_label}", "decided_at": at}
    )
    updated = record.model_copy(
        update={
            "overrides": [*record.overrides, entry],
            "outcome": outcome,
            "status": RecordStatus.OVERRIDDEN,
        }
    )
    return seal(updated)
