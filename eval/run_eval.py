"""Run the agent over the eval boxes and save one evidence record per box.

    python eval/run_eval.py --split dev --run dev-v1
    python eval/run_eval.py --split test --run test-v1            # the held-out run
    python eval/run_eval.py --split test --run test-v1-order --reveal-order   # ablation

Model answers are cached by photo + prompt + model, so re-running costs no quota. Boxes
that failed (e.g. rate limit) come back as PENDING records; just run the command again.
Photos that fail the quality gate are still verified (forced), because in the eval we
want to see what the agent does with them; the gate result is kept on the record.
"""

from __future__ import annotations

import argparse
import json
import time

from common import EVAL_DIR, ORG, ROOT, load_manifest

from pack_manager.catalogue import load_org_catalogue
from pack_manager.config import get_settings
from pack_manager.models import Decision
from pack_manager.pipeline import Photo, prepare_photos, verify_box
from pack_manager.vision.gemini import GeminiPerceiver


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--run", required=True, help="name of the results folder, e.g. test-v1")
    ap.add_argument("--reveal-order", action="store_true", help="ablation: tell the model the order")
    ap.add_argument("--delay", type=float, default=4.0, help="seconds between uncached model calls")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    settings = get_settings().model_copy(update={"gemini_max_retries": 3})
    catalogue, root = load_org_catalogue(ROOT / settings.catalogue_dir, ORG)
    perceiver = GeminiPerceiver(settings)
    out = EVAL_DIR / "results" / args.run / "records"
    out.mkdir(parents=True, exist_ok=True)
    (out.parent / "run.json").write_text(json.dumps({
        "split": args.split, "reveal_order": args.reveal_order, "model": settings.gemini_model,
        "match_threshold": settings.match_threshold, "visibility_threshold": settings.visibility_threshold,
    }, indent=2), encoding="utf-8")

    boxes = load_manifest(args.split)
    if args.limit:
        boxes = boxes[: args.limit]
    pending = 0
    for i, box in enumerate(boxes, 1):
        if not box.photos:
            print(f"[{i}/{len(boxes)}] {box.box_id}: no photos in eval/boxes/{box.box_id}/, skipped")
            continue
        prepared = prepare_photos([Photo(p.read_bytes()) for p in box.photos[: settings.max_box_photos]], settings)
        perceiver.order_hint = box.expected if args.reveal_order else None
        record = verify_box(box.order, prepared, catalogue, perceiver, settings,
                            operator_label="eval", catalogue_root=root, force_quality=True)
        (out / f"{box.box_id}.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
        cached = (record.observations or {}).get("cached_response")
        d = record.outcome.decision
        pending += d == Decision.PENDING
        print(f"[{i}/{len(boxes)}] {box.box_id} {box.scenario:20} truth={box.decision_truth:13} agent={d.value}"
              + (" (cached)" if cached else ""))
        if not cached and i < len(boxes):
            time.sleep(args.delay)
    print(f"\nSaved to {out}. Pending (model failed): {pending}. Re-run to retry them.")
    print(f"Next: python eval/metrics.py --run {args.run}")


if __name__ == "__main__":
    main()
