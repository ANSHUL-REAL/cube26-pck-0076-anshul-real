"""Copy photos from the phone into eval/boxes/<box_id>/, in manifest order.

    python eval/import_photos.py --from "D:/phone/DCIM/Camera" --split test            # preview
    python eval/import_photos.py --from "D:/phone/DCIM/Camera" --split test --apply    # copy
    python eval/import_photos.py --from "D:/phone/DCIM/Camera" --split all             # D01..T50 in one go

Photos are sorted by the time they were taken (EXIF, else file time) and grouped into
boxes: a new box starts when more than --gap seconds pass between two photos (or use
--per-box N for a fixed number per box). Groups are matched to the manifest rows of the
split, in order, starting at --start. By default they fill the first run of boxes with no
photos yet, and stop before the next box that already has photos (never overwritten
unless you name it with --start).

It always writes eval/import_check_<split>.html: each box's order and real contents next
to its photos, so you can confirm at a glance that nothing shifted by one. Source files
are never moved or deleted.

Copies are saved as upright JPEGs, at most 1600 px on the long side (what the model is sent
anyway), with all metadata removed (EXIF, XMP, comments; only the colour profile is kept):
phone photos carry GPS location, and these files end up in a public repository.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
from datetime import datetime
from pathlib import Path

from common import EVAL_DIR, PHOTO_EXT, load_manifest
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

EXIF_IFD, DATETIME_ORIGINAL, DATETIME = 0x8769, 36867, 306


def taken_at(path: Path) -> datetime:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            raw = exif.get_ifd(EXIF_IFD).get(DATETIME_ORIGINAL) or exif.get(DATETIME)
        if raw:
            return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def group(photos: list[tuple[datetime, Path]], gap: float, per_box: int) -> list[list[tuple[datetime, Path]]]:
    groups: list[list[tuple[datetime, Path]]] = []
    for i, item in enumerate(photos):
        if per_box:
            new = i % per_box == 0
        else:
            new = not groups or (item[0] - groups[-1][-1][0]).total_seconds() > gap
        if new:
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


def save_clean(src: Path, dest: Path, max_side: int) -> None:
    """Upright, resized JPEG with no metadata (no EXIF/GPS, device info, XMP or comments)."""
    with Image.open(src) as img:
        # The colour profile is kept only when it still matches the pixels (an RGB source).
        icc = img.info.get("icc_profile") if img.mode in ("RGB", "RGBA") else None
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        img.info = {}  # Pillow would otherwise copy a JPEG comment into the new file
        img.save(dest, "JPEG", quality=90, **({"icc_profile": icc} if icc else {}))


def thumb(path: Path, side: int = 360) -> str:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((side, side))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=75)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def contact_sheet(pairs, split: str) -> Path:
    rows = []
    for box, photos in pairs:
        imgs = "".join(f'<img src="{thumb(p)}" title="{html.escape(p.name)} · {t:%H:%M:%S}">' for t, p in photos)
        rows.append(
            f"<tr><td><b>{html.escape(box.box_id)}</b><div class=m>{html.escape(box.scenario)}</div></td>"
            f"<td><div class=m>order</div>{html.escape(box.order_lines)}<div class=m>really packed</div>"
            f"{html.escape(box.actual_contents)}</td><td>{imgs or '<i>no photos</i>'}</td></tr>"
        )
    out = EVAL_DIR / f"import_check_{split}.html"
    out.write_text(
        "<!doctype html><meta charset=utf-8><title>Import check</title><style>"
        "body{font:14px system-ui;margin:20px;color:#101828}td{border-top:1px solid #e4e7ec;padding:10px;vertical-align:top}"
        "img{height:150px;border-radius:8px;margin:0 6px 6px 0}.m{color:#667085;font-size:12px;margin-top:4px}</style>"
        f"<h2>Check that every row's photos show that box</h2><table>{''.join(rows)}</table>",
        encoding="utf-8",
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="folder with the phone's photos")
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"],
                    help="all = practice and test boxes in manifest order, for one shoot")
    ap.add_argument("--gap", type=float, default=25, help="seconds between photos that start a new box")
    ap.add_argument("--per-box", type=int, default=0, help="fixed number of photos per box instead of --gap")
    ap.add_argument("--start", help="first box id to fill, e.g. T31 (default: first box without photos)")
    ap.add_argument("--after", help="ignore photos taken before this time, e.g. '2026-09-29 14:00'")
    ap.add_argument("--max-side", type=int, default=1600, help="long side of the saved copies, in pixels")
    ap.add_argument("--apply", action="store_true", help="actually copy the files")
    args = ap.parse_args()

    src = Path(args.src)
    files = [p for p in src.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_EXT]
    photos = sorted((taken_at(p), p) for p in files)
    if args.after:
        cutoff = datetime.fromisoformat(args.after)
        photos = [x for x in photos if x[0] >= cutoff]
    if not photos:
        raise SystemExit(f"No photos found in {src}.")

    boxes = load_manifest(args.split)
    if args.start:
        ids = [b.box_id for b in boxes]
        if args.start not in ids:
            raise SystemExit(f"{args.start} is not a {args.split} box in the manifest.")
        boxes = boxes[ids.index(args.start):]
    else:
        # One contiguous run of empty boxes: the photos were taken in manifest order, so
        # skipping a box that already has photos would shift every later box by one.
        first = next((i for i, b in enumerate(boxes) if not b.photos), len(boxes))
        end = next((i for i in range(first, len(boxes)) if boxes[i].photos), len(boxes))
        if end < len(boxes):
            print(f"Filling {boxes[first].box_id} to {boxes[end - 1].box_id}; stopping before {boxes[end].box_id}, "
                  "which already has photos. Use --start to go past it.")
        boxes = boxes[first:end]

    groups = group(photos, args.gap, args.per_box)
    pairs = list(zip(boxes, groups))
    for box, g in pairs:
        names = ", ".join(p.name for _, p in g)
        print(f"{box.box_id:6} {box.scenario:20} {len(g)} photo(s)  {g[0][0]:%H:%M:%S}  {names}")
    if len(groups) != len(boxes):
        print(f"\nWARNING: {len(groups)} photo groups but {len(boxes)} boxes to fill. "
              "Check the contact sheet; adjust --gap, --per-box, --start or --after.")
    sheet = contact_sheet(pairs, args.split)
    print(f"\nContact sheet: {sheet}")

    if not args.apply:
        print("Preview only. Add --apply to copy the files.")
        return
    for box, g in pairs:
        folder = EVAL_DIR / "boxes" / box.box_id
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*"):
            if old.suffix.lower() in PHOTO_EXT:
                old.unlink()
        for n, (_, p) in enumerate(g, 1):
            save_clean(p, folder / f"{n}.jpg", args.max_side)
    print(f"Copied photos for {len(pairs)} boxes into {EVAL_DIR / 'boxes'}.")


if __name__ == "__main__":
    main()
