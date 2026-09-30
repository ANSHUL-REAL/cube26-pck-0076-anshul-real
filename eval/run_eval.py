"""Run the agent over the eval boxes and save one evidence record per box.

    python eval/run_eval.py --split dev --run dev-v1
    python eval/freeze.py --split test                            # first, once labels are in; commit it
    python eval/run_eval.py --split test --run test-v1            # the held-out run
    python eval/run_eval.py --split test --run test-v1-order --reveal-order   # ablation
    python eval/run_eval.py --split dev --run dev-oracle --oracle      # the rules alone, no model

--oracle skips the model: the agent is given exactly what the manifest says was packed, as a
perfect object list. It measures the decision rules on their own (what's left over is the
model's share of the errors) and costs nothing, so it's also a dry run of the whole pipeline.

--split all includes the test boxes, so it needs the same freeze as --split test.

Model answers are cached by photo + prompt + model, so re-running costs no quota. Boxes
that failed (e.g. rate limit) come back as PENDING records; just run the command again.
Photos that fail the quality gate are still verified (forced), because in the eval we
want to see what the agent does with them; the gate result is kept on the record.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from common import EVAL_DIR, ORG, ROOT, eval_settings, load_manifest
from freeze import differences, fingerprint, frozen_path

from pack_manager.catalogue import load_org_catalogue
from pack_manager.models import Decision
from pack_manager.pipeline import Photo, prepare_photos, verify_box
from pack_manager.vision.base import PerceptionError
from pack_manager.vision.gemini import GeminiPerceiver
from pack_manager.vision.oracle import OraclePerceiver


def oracle_for(box) -> OraclePerceiver:
    """Perfect perception of what was physically packed; OTHER is a product not in the catalogue."""
    seen = {sku: n for sku, n in box.actual.items() if sku != "OTHER"}
    return OraclePerceiver(seen, ["a product that isn't in the catalogue"] * box.actual.get("OTHER", 0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--run", required=True, help="name of the results folder, e.g. test-v1")
    ap.add_argument("--reveal-order", action="store_true", help="ablation: tell the model the order")
    ap.add_argument("--oracle", action="store_true", help="skip the model: perfect perception from the manifest")
    ap.add_argument("--delay", type=float, default=4.0, help="seconds between uncached model calls")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--unfrozen", action="store_true",
                    help="run the test boxes (split test or all) without a matching freeze; "
                         "the run is then marked as not held-out")
    args = ap.parse_args()

    settings = eval_settings()
    frozen = None
    # Any run that shows the agent a test box must match the freeze, not only --split test.
    if args.split == "test" or (args.split == "all" and load_manifest("test")):
        path = frozen_path("test")
        if path.exists():
            frozen = json.loads(path.read_text(encoding="utf-8"))
            diff = differences(frozen, fingerprint("test", settings))
            frozen = {"file": path.relative_to(ROOT).as_posix(), "frozen_at": frozen["frozen_at"], "matches": not diff,
                      "changed_since": diff}
        if not (frozen and frozen["matches"]) and not args.unfrozen:
            raise SystemExit(
                f"--split {args.split} runs the test boxes, but the test set isn't frozen, "
                "or something changed since it was:\n  "
                + ("\n  ".join(frozen["changed_since"]) if frozen else "no eval/frozen-test.json")
                + "\nFreeze it (python eval/freeze.py --split test) and commit that before the held-out run, "
                "or pass --unfrozen: the run is then reported as not held-out.")
    if args.oracle and args.reveal_order:
        raise SystemExit("--oracle doesn't use the model, so --reveal-order means nothing with it.")
    catalogue, root = load_org_catalogue(ROOT / settings.catalogue_dir, ORG)
    try:
        perceiver = None if args.oracle else GeminiPerceiver(settings)
    except PerceptionError as exc:
        raise SystemExit(f"{exc} Add it to .env, or use --oracle for a dry run without the model.") from None
    out = EVAL_DIR / "results" / args.run / "records"
    out.mkdir(parents=True, exist_ok=True)
    run_file = out.parent / "run.json"
    # Keep the time of the FIRST run: re-running to retry pending boxes mustn't move it later,
    # because the report checks that every human label was made before the agent ran.
    first = json.loads(run_file.read_text(encoding="utf-8")).get("started_at") if run_file.exists() else None
    run_file.write_text(json.dumps({
        "split": args.split, "reveal_order": args.reveal_order,
        "perceiver": "oracle" if args.oracle else "model",
        "model": "none (oracle)" if args.oracle else settings.gemini_model,
        "match_threshold": settings.match_threshold, "visibility_threshold": settings.visibility_threshold,
        "started_at": first or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "frozen": frozen,
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
        if args.oracle:
            perceiver = oracle_for(box)
        else:
            perceiver.order_hint = box.expected if args.reveal_order else None
        record = verify_box(box.order, prepared, catalogue, perceiver, settings,
                            operator_label="eval", catalogue_root=root, force_quality=True)
        (out / f"{box.box_id}.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
        cached = (record.observations or {}).get("cached_response")
        d = record.outcome.decision
        pending += d == Decision.PENDING
        print(f"[{i}/{len(boxes)}] {box.box_id} {box.scenario:20} truth={box.decision_truth:13} agent={d.value}"
              + (" (cached)" if cached else ""))
        if not cached and not args.oracle and i < len(boxes):
            time.sleep(args.delay)
    print(f"\nSaved to {out}. Pending (model failed): {pending}. Re-run to retry them.")
    print(f"Next: python eval/metrics.py --run {args.run}")


if __name__ == "__main__":
    main()
