"""Regenerate the published contract: the JSON Schema and the example records.

    python contract/build_contract.py
    python contract/build_contract.py --from-run test-v1   # real records from an eval run

The schema comes straight from the pydantic model the agent writes (pack_manager.models.
EvidenceRecord), so it can't drift from the code; tests/test_contract.py checks that.
The examples are produced by the real pipeline (quality gate, decision engine, hashing,
override) with a scripted perception instead of the vision model, on a synthetic photo.
They show the record's shape, not real model output. After the held-out run, --from-run replaces
each of them with a real record of the same outcome from that run (the hash is checked first).

Each example is also written in the organisers' Evidence Contract 1.1 shape to examples-1.1/, the
shape the /v1 API returns (pack_manager/contract.py).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from pack_manager.catalogue import load_catalogue  # noqa: E402
from pack_manager.config import Settings  # noqa: E402
from pack_manager.contract import to_contract  # noqa: E402
from pack_manager.evidence import apply_override, verify  # noqa: E402
from pack_manager.models import (  # noqa: E402
    Decision,
    DetectedObject,
    EvidenceRecord,
    Order,
    OrderLine,
    Perception,
    Scene,
    SkuCount,
)
from pack_manager.pipeline import Photo, prepare_photos, verify_box  # noqa: E402
from pack_manager.vision.base import PerceptionError  # noqa: E402
from pack_manager.vision.prompt import PROMPT_VERSION  # noqa: E402

SCHEMA_PATH = HERE / "pack-evidence-record.schema.json"
MODEL = "gemini-2.5-flash"
AT = datetime(2026, 9, 28, 10, 30, tzinfo=timezone.utc)


def schema() -> dict:
    s = EvidenceRecord.model_json_schema()
    s["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    s["$id"] = "cube.evidence.v1/pack-evidence-record"
    s["description"] = (
        "Pack Manager evidence record. Field names follow the handbook's evidence contract "
        "(section 9). One record per outbound box. See contract/README.md."
    )
    return s


class Scripted:
    def __init__(self, objects, counts, scene, fail=False):
        self.objects, self.counts, self.scene, self.fail = objects, counts, scene, fail

    def perceive(self, photos, candidates, allowed_inserts, catalogue_root):
        if self.fail:
            raise PerceptionError("timed out after 25 s")
        return Perception(
            objects=self.objects, counts=self.counts, scene=self.scene,
            candidates=[c.sku for c in candidates], model_version=MODEL, prompt_version=PROMPT_VERSION,
            latency_ms=3180, usage={"input_tokens": 5210, "output_tokens": 412, "thinking_tokens": 0,
                                    "total_tokens": 5622},
        )


def o(i, sku=None, conf=0.93, box=None, desc="", cls=None, feature="", hidden=False, alts=None):
    return DetectedObject(
        object_id=f"o{i}", box_2d=box, description=desc, sku=sku, confidence=conf,
        classification=cls or ("CANDIDATE" if sku else "UNKNOWN_PRODUCT"),
        deciding_feature=feature, partially_hidden=hidden, alternative_skus=alts or [],
    )


CLEAR = Scene(box_interior_fully_visible=True, items_may_be_hidden=False, visibility_confidence=0.95)


def photo() -> bytes:
    import io

    from PIL import Image

    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:1200, 0:1600]
    img = 110 + (((yy // 50) + (xx // 50)) % 2 * 60)[..., None] + rng.integers(0, 25, (1200, 1600, 3))
    buf = io.BytesIO()
    Image.fromarray(img.astype("uint8")).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def main() -> None:
    SCHEMA_PATH.write_text(json.dumps(schema(), indent=2) + "\n", encoding="utf-8")
    settings = Settings(_env_file=None, gemini_api_key=None, gemini_model=MODEL,
                        cost_per_1m_input_usd=0.30, cost_per_1m_output_usd=2.50)
    catalogue = load_catalogue(ROOT / "catalogue" / "sample")
    prepared = prepare_photos([Photo(photo())], settings)

    def order(oid, unit, *lines):
        return Order(order_id=oid, organization_id="org_demo_alpha", client_id="client_seller_01",
                     unit_id=unit, channel="shopify", lines=[OrderLine(sku=s, qty=q) for s, q in lines])

    cases = {
        "seal": (
            order("ORD-DUMMY-50012", "UNIT-0012", ("SKU-MUG-11", 1), ("SKU-LEASH-6FT", 1)),
            Scripted([o(1, "SKU-MUG-11", 0.94, [120, 90, 610, 480], "white box printed with two mugs"),
                      o(2, "SKU-LEASH-6FT", 0.91, [300, 520, 760, 900], "coiled red nylon leash"),
                      o(3, None, 0.97, [650, 80, 940, 430], "printed packing slip", cls="NON_PRODUCT")],
                     [SkuCount(sku="SKU-MUG-11", count=1, count_certain=True),
                      SkuCount(sku="SKU-LEASH-6FT", count=1, count_certain=True)], CLEAR),
            None,
        ),
        "stop_and_fix": (
            order("ORD-DUMMY-50044", "UNIT-0044", ("SKU-CANDLE-3", 1)),
            Scripted([o(1, "SKU-BOTTLE-750", 0.9, [180, 300, 820, 640], "black steel bottle with screw lid",
                        feature="bottle shape, no gift box")],
                     [SkuCount(sku="SKU-BOTTLE-750", count=1, count_certain=True)], CLEAR),
            None,
        ),
        "uncertain": (
            order("ORD-DUMMY-50016", "UNIT-0016", ("SKU-TOWEL-BLU", 2)),
            Scripted([o(1, "SKU-TOWEL-BLU", 0.92, [200, 150, 780, 850], "folded blue towel on top", hidden=False),
                      o(2, "SKU-TOWEL-BLU", 0.55, [720, 160, 800, 840], "edge of blue fabric under it",
                        hidden=True)],
                     [SkuCount(sku="SKU-TOWEL-BLU", count=2, count_certain=False,
                               reason="Second towel is mostly hidden under the first")],
                     Scene(box_interior_fully_visible=True, items_may_be_hidden=True, visibility_confidence=0.6,
                           notes="Towels are stacked")),
            None,
        ),
        "pending": (
            order("ORD-DUMMY-50021", "UNIT-0021", ("SKU-PUZZLE-500", 1)),
            Scripted([], [], CLEAR, fail=True),
            None,
        ),
        "overridden": (
            order("ORD-DUMMY-50016", "UNIT-0016", ("SKU-TOWEL-BLU", 2)),
            None,  # filled below from the uncertain case
            ("SEAL", "hidden_item_verified", "Lifted the top towel; two towels in the box."),
        ),
    }
    records: dict[str, EvidenceRecord] = {}
    for name, (od, perceiver, override) in cases.items():
        if override:
            new, reason, note = override
            record = apply_override(records["uncertain"], Decision(new), reason, "op_alpha", note=note,
                                    at=datetime(2026, 9, 28, 10, 31, 12, tzinfo=timezone.utc))
        else:
            record = verify_box(od, prepared, catalogue, perceiver, settings, operator_label="op_alpha",
                                catalogue_root=ROOT / "catalogue" / "sample", captured_at=AT)
        records[name] = record
        (HERE / "examples" / f"{name}.json").write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"{name:13} {record.outcome.decision.value:13} {record.status.value:15} {record.record_id}")
    print(f"Wrote {SCHEMA_PATH.name} and {len(records)} examples.")


def from_run(run: str) -> None:
    """Swap the scripted examples for real records from an eval run, one per outcome."""
    found: dict[str, EvidenceRecord] = {}
    for path in sorted((ROOT / "eval" / "results" / run / "records").glob("*.json")):
        record = EvidenceRecord.model_validate_json(path.read_text(encoding="utf-8"))
        if not verify(record):
            raise SystemExit(f"{path.name}: content hash doesn't match; not using it.")
        found.setdefault(record.outcome.decision.value, record)
    for decision, name in [("SEAL", "seal"), ("STOP_AND_FIX", "stop_and_fix"),
                           ("UNCERTAIN", "uncertain"), ("PENDING", "pending")]:
        record = found.get(decision)
        if record is None:
            print(f"{name:13} no {decision} record in run {run}; kept the scripted example")
            continue
        (HERE / "examples" / f"{name}.json").write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"{name:13} real record {record.record_id} ({record.subject.get('order_id')})")
    if "UNCERTAIN" not in found:
        print("overridden    kept the scripted example (eval runs have no hand decisions)")
        return
    # Eval runs have no hand decisions, so the example applies one to the real UNCERTAIN record.
    # It is the decision the box's ground truth calls for (the manifest), written the way a
    # packer would record it: an illustration of the override, not a real person's check.
    uncertain = found["UNCERTAIN"]
    box = uncertain.subject.get("order_id", "").removeprefix("EVAL-")
    with (ROOT / "eval" / "manifest.csv").open(encoding="utf-8") as f:
        truth = {row["box_id"]: row for row in csv.DictReader(f)}.get(box)
    if truth and truth["scenario"] == "correct":
        new, note = Decision.SEAL, "Checked under the netting: every ordered item is there."
    else:
        new, note = Decision.STOP_AND_FIX, "Checked under the netting: " + (
            truth["notes"].split(". ", 1)[-1] if truth else "the box doesn't match the order.")
    record = apply_override(uncertain, new, "hidden_item_verified", "op_alpha", note=note,
                            at=uncertain.captured_at + timedelta(minutes=2))
    (HERE / "examples" / "overridden.json").write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"overridden    a {new.value} hand decision (as the manifest says), on real record {record.record_id}")


def _stored_sizes(record: EvidenceRecord) -> dict[str, int]:
    """Bytes of each stored photo, found by preparing the photos the example was made from
    (the eval box's photos, or the synthetic one) and matching their hashes."""
    box = record.subject.get("order_id", "").removeprefix("EVAL-")
    sources = [photo()] + [f.read_bytes() for f in sorted((ROOT / "eval" / "boxes" / box).glob("*.jpg"))]
    runs = [Settings(_env_file=None, gemini_api_key=None),
            Settings(_env_file=None, gemini_api_key=None, min_side_px=200, blur_min_var=3.0)]
    by_hash = {}
    for data in sources:
        for settings in runs:
            try:
                for p in prepare_photos([Photo(data)], settings):
                    by_hash[p.sha256] = len(p.jpeg)
            except Exception:  # noqa: BLE001 - a source that doesn't prepare just isn't a match
                pass
    return {i.image_id: by_hash[i.sha256] for i in record.images if i.sha256 in by_hash}


def write_contract_examples() -> None:
    """Every example in the Evidence Contract 1.1 shape."""
    out = HERE / "examples-1.1"
    out.mkdir(exist_ok=True)
    catalogues = [load_catalogue(d) for d in (ROOT / "catalogue" / "org_bench_abid", ROOT / "catalogue" / "sample")]
    for path in sorted((HERE / "examples").glob("*.json")):
        record = EvidenceRecord.model_validate_json(path.read_text(encoding="utf-8"))
        skus = [line["sku"] for line in record.subject["expected_lines"]]
        catalogue = next((c for c in catalogues if all(c.get(s) for s in skus)), None)
        sizes = _stored_sizes(record)
        missing = [i.image_id for i in record.images if i.image_id not in sizes]
        if missing:
            raise SystemExit(f"{path.name}: can't find the photo for image {missing[0]}, so its size is unknown.")
        contract = to_contract(record, image_bytes=sizes, catalogue=catalogue)
        (out / path.name).write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote the examples in Evidence Contract 1.1 shape to {out.name}/.")


if __name__ == "__main__":
    (HERE / "examples").mkdir(exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-run", help="use real records from eval/results/<run>/records")
    args = ap.parse_args()
    main()
    if args.from_run:
        from_run(args.from_run)
    write_contract_examples()
