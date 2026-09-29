"""Freeze the held-out set before the agent sees it.

    python eval/freeze.py --split test

Run this once both labellers' files are in eval/labels/, and commit the file it writes
(eval/frozen-<split>.json) BEFORE running the agent on the split. It records every setting
except secrets (model, thresholds, quality gate, photo sizes ...) and the prompt version,
plus SHA-256 hashes of the agent's code and the eval code that feeds it, the manifest rows,
every box photo, every catalogue file (reference photos included) and the label files.
run_eval.py refuses a test run (or an "all" run, which includes the test boxes) that
doesn't match it, so nothing can be changed between labelling and running without it showing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from common import EVAL_DIR, ORG, ROOT, eval_settings, load_manifest

from pack_manager.config import Settings
from pack_manager.vision.prompt import PROMPT_VERSION

# Settings left out of the freeze: secrets (the freeze file is committed) and ones that
# can't change a result. Anything else, including settings added later, is frozen.
NOT_FROZEN = {"gemini_api_key", "database_url", "database_admin_url", "pack_app_db_password",
              "session_secret", "cache_dir", "daily_checks_per_org", "secure_cookies"}
SECRET_WORDS = ("key", "secret", "password", "url")
EVAL_CODE = ["common.py", "run_eval.py"]  # decide what the agent is given in an eval run
SKIP_FILES = {"thumbs.db", "desktop.ini"}  # written by Windows Explorer, never read


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frozen_path(split: str):
    return EVAL_DIR / f"frozen-{split}.json"


def frozen_settings(settings: Settings) -> dict:
    return {k: v for k, v in settings.model_dump().items()
            if k not in NOT_FROZEN and not any(w in k for w in SECRET_WORDS)}


def _tree(folder: Path, base: Path) -> dict[str, str]:
    """{path relative to base: SHA-256} for every file under folder."""
    if not folder.is_dir():
        return {}
    return {p.relative_to(base).as_posix(): _sha(p.read_bytes()) for p in sorted(folder.rglob("*"))
            if p.is_file() and not p.name.startswith(".") and p.name.lower() not in SKIP_FILES}


def fingerprint(split: str, settings: Settings) -> dict:
    """Everything that decides the result of a run on this split, hashed."""
    boxes = load_manifest(split)
    rows = "\n".join("|".join([b.box_id, b.split, b.scenario, b.order_lines, b.actual_contents, b.conditions])
                     for b in boxes)
    code = {p.relative_to(ROOT).as_posix(): _sha(p.read_bytes()) for p in sorted((ROOT / "pack_manager").rglob("*.py"))}
    code |= {f"eval/{name}": _sha((EVAL_DIR / name).read_bytes()) for name in EVAL_CODE if (EVAL_DIR / name).exists()}
    # The org's own catalogue and the organisers' sample one, which it is merged with.
    catalogue_dir = ROOT / settings.catalogue_dir
    return {
        "config": {"prompt_version": PROMPT_VERSION, **frozen_settings(settings)},
        "code_sha256": code,
        "boxes": len(boxes),
        "manifest_rows_sha256": _sha(rows.encode("utf-8")),
        "photos_sha256": {b.box_id: [_sha(p.read_bytes()) for p in b.photos] for b in boxes},
        "catalogue_files_sha256": _tree(catalogue_dir / ORG, catalogue_dir) | _tree(catalogue_dir / "sample", catalogue_dir),
        "labels_sha256": {p.name: _sha(p.read_bytes()) for p in sorted((EVAL_DIR / "labels").glob("*.csv"))},
    }


def differences(frozen: dict, now: dict) -> list[str]:
    """One line per part that changed, naming the setting, file or box (at most 8 per line)."""
    out = []
    for key, value in now.items():
        if frozen.get(key) != value:
            if isinstance(value, dict) and isinstance(frozen.get(key), dict):
                changed = sorted(k for k in set(value) | set(frozen[key]) if value.get(k) != frozen[key].get(k))
                more = f" and {len(changed) - 8} more" if len(changed) > 8 else ""
                out.append(f"{key}: {', '.join(changed[:8])}{more}")
            else:
                out.append(key)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["dev", "test"])
    args = ap.parse_args()
    now = fingerprint(args.split, eval_settings())
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
    print(f"Froze {now['boxes']} {args.split} boxes, {len(now['labels_sha256'])} label files, "
          f"{len(now['catalogue_files_sha256'])} catalogue files, model {now['config']['gemini_model']}, "
          f"prompt {now['config']['prompt_version']} -> {path.relative_to(ROOT)}")
    print("Commit it now, before running the agent:  git add eval/ && git commit -m \"Freeze the test set\"")


if __name__ == "__main__":
    main()
