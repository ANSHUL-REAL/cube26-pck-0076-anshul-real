"""Shared helpers for the eval scripts: manifest, ground truth, photos."""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
sys.path.insert(0, str(ROOT))

from pack_manager.models import Order, parse_lines  # noqa: E402

ORG = "org_demo_alpha"
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
SCENARIOS = [
    "correct", "missing", "wrong_item", "extra", "wrong_qty",
    "identical_multiples", "similar_products", "ambiguous_photo", "adversarial",
]


def counts(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in parse_lines(text or ""):
        out[line.sku] = out.get(line.sku, 0) + line.qty
    return out


@dataclass
class Box:
    box_id: str
    split: str
    scenario: str
    order_lines: str
    actual_contents: str
    conditions: str
    notes: str

    @property
    def order(self) -> Order:
        return Order(order_id=f"EVAL-{self.box_id}", organization_id=ORG, lines=parse_lines(self.order_lines))

    @property
    def photos(self) -> list[Path]:
        folder = EVAL_DIR / "boxes" / self.box_id
        return sorted(p for p in folder.glob("*") if p.suffix.lower() in PHOTO_EXT) if folder.exists() else []

    # ---- ground truth from what was physically packed (not from the photos)
    @property
    def expected(self) -> dict[str, int]:
        return counts(self.order_lines)

    @property
    def actual(self) -> dict[str, int]:
        return counts(self.actual_contents)

    @property
    def hidden(self) -> bool:
        """An item was (partly) under another item or filler when photographed."""
        return "hidden" in {w.strip().lower() for w in self.conditions.split(";")}

    def line_truth(self, sku: str) -> str:
        return "PASS" if self.actual.get(sku, 0) == self.expected[sku] else "FAIL"

    @property
    def unexpected_truth(self) -> str:
        return "FAIL" if any(s not in self.expected for s in self.actual) else "PASS"

    @property
    def decision_truth(self) -> str:
        ok = all(self.line_truth(s) == "PASS" for s in self.expected) and self.unexpected_truth == "PASS"
        return "SEAL" if ok else "STOP_AND_FIX"


def load_manifest(split: str | None = None) -> list[Box]:
    path = EVAL_DIR / "manifest.csv"
    with open(path, newline="", encoding="utf-8") as f:
        boxes = [
            Box(**{k: (r.get(k) or "").strip() for k in Box.__dataclass_fields__})
            for r in csv.DictReader(f)
            if (r.get("box_id") or "").strip() and not r["box_id"].startswith("#")
        ]
    return [b for b in boxes if split in (None, "all") or b.split == split]
