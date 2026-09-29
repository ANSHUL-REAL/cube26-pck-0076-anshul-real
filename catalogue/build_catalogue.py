"""Build an organisation's catalogue.json from a spreadsheet and folders of product photos.

    python catalogue/build_catalogue.py --org org_demo_alpha                      # CSV -> JSON
    python catalogue/build_catalogue.py --org org_demo_alpha --photos "D:/products"  # + import photos

1. Fill catalogue/<org>/products.csv (created with the right columns on first run; open it
   in Excel or Google Sheets). One row per product.
2. Optional: put each product's reference photos in a folder named exactly like its SKU,
   e.g. D:/products/CAP-BLUE/*.jpg, and pass --photos D:/products. They are copied upright,
   resized and with EXIF (GPS) removed into catalogue/<org>/images/<SKU>/1.jpg, 2.jpg ...
3. The script writes catalogue/<org>/catalogue.json. Look-alike links are made two-way.

CSV columns (only sku and title are required):
  sku, title, attributes ("colour=blue; size=L"), sellable_unit, distinguishing_features,
  confusable_with ("CAP-RED; CAP-GRN"), component_lookalikes, components
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pack_manager.models import DEFAULT_ALLOWED_INSERTS, Catalogue  # noqa: E402

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

COLUMNS = ["sku", "title", "attributes", "sellable_unit", "distinguishing_features",
           "confusable_with", "component_lookalikes", "components"]
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def split_list(text: str) -> list[str]:
    return [p.strip() for p in (text or "").replace(",", ";").split(";") if p.strip()]


def split_attrs(text: str) -> dict[str, str]:
    out = {}
    for part in split_list(text):
        key, _, value = part.partition("=")
        if value:
            out[key.strip()] = value.strip()
    return out


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Column names and rows of products.csv as saved by Excel or Google Sheets.

    Excel's "CSV UTF-8" starts with a byte-order mark and its plain "CSV (Comma delimited)"
    is Windows-1252, so both are accepted. Column names are matched without case or outer
    spaces ("SKU", " Title ", "Sellable unit" all work).
    """
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    reader = csv.reader(io.StringIO(text, newline=""))
    columns = [c.strip().lower().replace(" ", "_") for c in next(reader, [])]
    rows = [{k: v.strip() for k, v in zip(columns, row) if k} for row in reader]
    return columns, rows


def save_clean(src: Path, dest: Path, max_side: int) -> None:
    """Upright, resized JPEG with no metadata (no EXIF/GPS, device info, XMP or comments)."""
    with Image.open(src) as img:
        # The colour profile is kept only when it still matches the pixels (an RGB source).
        icc = img.info.get("icc_profile") if img.mode in ("RGB", "RGBA") else None
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        img.info = {}  # Pillow would otherwise copy a JPEG comment into the new file
        img.save(dest, "JPEG", quality=90, **({"icc_profile": icc} if icc else {}))


def import_photos(src: Path, images: Path, skus: set[str], max_side: int) -> None:
    for folder in sorted(p for p in src.iterdir() if p.is_dir()):
        if folder.name not in skus:
            print(f"  skipped folder {folder.name}: no row with that sku in products.csv")
            continue
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in PHOTO_EXT)
        dest = images / folder.name
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.glob("*.jpg"):
            old.unlink()
        for n, path in enumerate(files, 1):
            save_clean(path, dest / f"{n}.jpg", max_side)
        print(f"  {folder.name}: {len(files)} photo(s)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True, help="organisation id, e.g. org_demo_alpha")
    ap.add_argument("--photos", help="folder with one sub-folder of photos per SKU")
    ap.add_argument("--max-side", type=int, default=1024)
    args = ap.parse_args()

    root = HERE / args.org
    csv_path = root / "products.csv"
    if not csv_path.exists():
        root.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            w.writerow(["CAP-BLUE", "Baseball Cap", "colour=blue", "one blue cotton cap",
                        "blue fabric; the red cap is the same shape", "CAP-RED", "", ""])
        raise SystemExit(f"Created {csv_path}. Fill in one row per product (replace the example), then run this again.")

    columns, rows = read_rows(csv_path)
    rows = [r for r in rows if r.get("sku")]
    if not rows:
        raise SystemExit(f"No products read from {csv_path}, so catalogue.json was not changed. The first row "
                         f"must name the columns, including sku and title (found: {', '.join(columns) or 'none'}), "
                         "and each product row needs a sku.")
    items = {}
    for r in rows:
        sku = r["sku"].strip()
        items[sku] = {
            "sku": sku,
            "title": (r.get("title") or sku).strip(),
            "attributes": split_attrs(r.get("attributes", "")),
            "sellable_unit": (r.get("sellable_unit") or "").strip(),
            "distinguishing_features": (r.get("distinguishing_features") or "").strip(),
            "confusable_with": split_list(r.get("confusable_with", "")),
            "component_lookalikes": split_list(r.get("component_lookalikes", "")),
            "components": split_list(r.get("components", "")),
        }

    if args.photos:
        print("Importing photos:")
        import_photos(Path(args.photos), root / "images", set(items), args.max_side)

    # look-alikes work both ways
    for sku, item in items.items():
        for other in item["confusable_with"]:
            if other in items and sku not in items[other]["confusable_with"]:
                items[other]["confusable_with"].append(sku)

    problems = []
    for sku, item in items.items():
        folder = root / "images" / sku
        item["reference_images"] = sorted(
            f"images/{sku}/{p.name}" for p in folder.glob("*.jpg")) if folder.exists() else []
        for other in item["confusable_with"] + item["component_lookalikes"]:
            if other not in items:
                problems.append(f"{sku}: look-alike {other} has no row")
        if not item["reference_images"]:
            problems.append(f"{sku}: no reference photos")
        if not item["sellable_unit"]:
            problems.append(f"{sku}: sellable_unit is empty (what does ONE unit look like?)")

    existing = root / "catalogue.json"
    inserts = DEFAULT_ALLOWED_INSERTS
    if existing.exists():
        inserts = json.loads(existing.read_text(encoding="utf-8")).get("allowed_inserts", inserts)
    data = {"organization_id": args.org, "allowed_inserts": inserts, "items": list(items.values())}
    Catalogue.model_validate(data)  # fail loudly on a bad shape
    existing.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pairs = sum(len(i["confusable_with"]) for i in items.values()) // 2
    print(f"Wrote {existing}: {len(items)} products, {pairs} look-alike pair(s).")
    for p in problems:
        print("  check:", p)


if __name__ == "__main__":
    main()
