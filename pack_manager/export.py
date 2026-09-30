"""Records as CSV rows in the organisers' pack_sample.csv shape, for the other pods.

The first eleven columns are exactly data/pack_sample.csv's, so Returns and Recovery can read
Pack's output with the parser they already wrote for the sample. The rest add what the sample
doesn't have: the agent's own decision, who made the final one, and the content hash.
"""

from __future__ import annotations

from collections import Counter

from .evidence import verify
from .models import EvidenceRecord

SAMPLE_COLUMNS = ["record_id", "unit_id", "org_id", "order_id", "channel", "order_lines", "observed_in_box",
                  "operator_verdict", "photo_refs", "operator_id", "captured_at"]
EXTRA_COLUMNS = ["agent_decision", "final_decision", "decided_by", "override_reason", "status",
                 "content_hash", "hash_verified"]
CSV_COLUMNS = SAMPLE_COLUMNS + EXTRA_COLUMNS


def _lines(counts: dict[str, int]) -> str:
    return ";".join(f"{sku}:{n}" for sku, n in counts.items())


def record_row(record: EvidenceRecord) -> dict[str, str]:
    subject = record.subject or {}
    obs = record.observations or {}
    seen: Counter[str] = Counter()
    for item in obs.get("detected_items") or []:
        if item.get("classification") == "CANDIDATE" and item.get("sku"):
            seen[item["sku"]] += 1
        elif item.get("classification") == "UNKNOWN_PRODUCT":
            seen["OTHER"] += 1
    last = record.box_overrides[-1] if record.box_overrides else None
    final = last.new_decision.value if last else record.outcome.decision.value
    # An override updates the outcome; the agent's own answer is kept in the first override.
    agent = record.overrides[0].original_decision.value if record.overrides else record.outcome.decision.value
    return {
        "record_id": record.record_id,
        "unit_id": subject.get("unit_id") or "",
        "org_id": record.organization_id,
        "order_id": subject.get("order_id") or "",
        "channel": subject.get("channel") or "",
        "order_lines": _lines({line["sku"]: line["qty"] for line in subject.get("expected_lines") or []}),
        "observed_in_box": _lines(dict(seen)),
        "operator_verdict": final.lower(),
        "photo_refs": ";".join(f"images/{i.image_id}" for i in record.images),
        "operator_id": (last.operator_label if last else record.operator_label) or "",
        "captured_at": record.captured_at.isoformat().replace("+00:00", "Z") if record.captured_at else "",
        "agent_decision": agent,
        "final_decision": final,
        "decided_by": "operator" if last else "agent",
        "override_reason": last.reason_code if last else "",
        "status": record.status.value,
        "content_hash": record.content_hash or "",
        "hash_verified": "yes" if verify(record) else "NO",
    }
