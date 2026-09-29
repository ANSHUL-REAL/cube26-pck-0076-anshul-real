"""Freeze the held-out set before the agent sees it.

    python eval/freeze.py --split test

Run this once both labellers' files are in eval/labels/, and commit the file it writes
(eval/frozen-<split>.json) BEFORE running the agent on the split. It records the model,
prompt version, thresholds and a hash of the agent's code, plus SHA-256 hashes of the
manifest rows, every box photo, the catalogue and the label files. run_eval.py refuses a
test run that doesn't match it, so nothing can be changed between labelling and running
without it showing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

from common import EVAL_DIR, ORG, ROOT, load_manifest

from pack_manager.config import Settings, get_settings
from pack_manager.vision.prompt import PROMPT_VERSION


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frozen_path(split: str):
    return EVAL_DIR / f"frozen-{split}.json"


def fingerprint(split: str, settings: Settings) -> dict:
    """Everything that decides the result of a run on this split, hashed."""
    boxes = load_manifest(split)
    rows = "\n".join("|".join([b.box_id, b.split, b.scenario, b.order_lines, b.actual_contents, b.conditions])
                     for b in boxes)
    code = b"".join(p.relative_to(ROOT).as_posix().encode() + p.read_bytes()
                    for p in sorted((ROOT / "pack_manager").rglob("*.py")))
    catalogue = ROOT / settings.catalogue_dir / ORG / "catalogue.json"
    return {
        "config": {
            "model": settings.gemini_model, "prompt_version": PROMPT_VERSION,
            "thinking_budget": settings.gemini_thinking_budget,
            "match_threshold": settings.match_threshold, "visibility_threshold": settings.visibility_threshold,
            "max_candidates": settings.max_candidates, "decoys_per_box": settings.decoys_per_box,
            "ref_images_per_sku": settings.ref_images_per_sku,
        },
        "agent_code_sha256": _sha(code),
        "boxes": len(boxes),
        "manifest_rows_sha256": _sha(rows.encode("utf-8")),
        "photos_sha256": {b.box_id: [_sha(p.read_bytes()) for p in b.photos] for b in boxes},
        "catalogue_sha256": _sha(catalogue.read_bytes()) if catalogue.exists() else None,
        "labels_sha256": {p.name: _sha(p.read_bytes()) for p in sorted((EVAL_DIR / "labels").glob("*.csv"))},
    }


def differences(frozen: dict, now: dict) -> list[str]:
    out = []
    for key, value in now.items():
        if frozen.get(key) != value:
            if isinstance(value, dict) and isinstance(frozen.get(key), dict):
                changed = sorted(k for k in set(value) | set(frozen[key]) if value.get(k) != frozen[key].get(k))
                out.append(f"{key}: {', '.join(changed)}")
            else:
                out.append(key)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["dev", "test"])
    args = ap.parse_args()
    now = fingerprint(args.split, get_settings())
    if now["boxes"] == 0:
        raise SystemExit(f"No {args.split} boxes in eval/manifest.csv.")
    missing = [b for b, photos in now["photos_sha256"].items() if not photos]
    if missing:
        raise SystemExit(f"These boxes have no photos yet: {', '.join(missing)}. Import the photos first.")
    if args.split == "test" and len(now["labels_sha256"]) < 2:
        raise SystemExit("Freeze after both labellers' files are in eval/labels/ (found "
                         f"{len(now['labels_sha256'])}). The freeze proves the labels existed before the run.")
    path = frozen_path(args.split)
    path.write_text(json.dumps({"split": args.split, "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                **now}, indent=2) + "\n", encoding="utf-8")
    print(f"Froze {now['boxes']} {args.split} boxes, {len(now['labels_sha256'])} label files, model "
          f"{now['config']['model']}, prompt {now['config']['prompt_version']} -> {path.relative_to(ROOT)}")
    print("Commit it now, before running the agent:  git add eval/ && git commit -m \"Freeze the test set\"")


if __name__ == "__main__":
    main()
