"""Build the eval set from the public Amazon Bin Image Dataset (ABID), instead of a home shoot.

    python eval/abid/build_abid.py sample          # download metadata for random bins (cache)
    python eval/abid/build_abid.py build           # pick bins, write the answer key, fetch photos

ABID: real photos of bins in Amazon fulfilment centres, each with Amazon's record of what the
bin holds (product names and quantities). Licence CC BY-NC-SA 3.0 US; see eval/abid/README.md.
https://registry.opendata.aws/amazon-bin-imagery/

A bin is a stand-in for an open box, and its record is what was physically packed. The
"order" for each box is written here, before the agent runs, from a fixed seed:
- correct: the order is exactly the record                        -> must SEAL
- missing: the order also asks for a product from another bin     -> must STOP
- extra:   the order leaves out one of the bin's products         -> must STOP
- wrong_qty: one line's quantity is off by one                    -> must STOP
- wrong_item: one product is swapped in the order for another bin's
  product, the most similar name available                        -> must STOP
Ground truth is Amazon's record, not two human labellers; it has some errors of its own.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL_DIR = HERE.parent
ROOT = EVAL_DIR.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from pack_manager.models import Catalogue, CatalogueItem  # noqa: E402

BASE = "https://aft-vbi-pds.s3.amazonaws.com"
LAST_BIN = 536434
CACHE = ROOT / ".cache" / "abid"
ORG = "org_bench_abid"
MIN_SIDE = 200  # the dataset's fixed warehouse camera; the gate's minimum is set to this
# The blur gate (Laplacian variance) was set for full-size phone photos. These small, soft
# warehouse photos score far lower while still readable. Set on the dev photos only, by eye,
# before any model run: all 20 were readable, the lowest scored 3.6.
BLUR_MIN = 3.0
TEST_MIX = [("correct", 24), ("missing", 6), ("extra", 6), ("wrong_qty", 7), ("wrong_item", 7)]
DEV_MIX = [("correct", 8), ("missing", 3), ("extra", 3), ("wrong_qty", 3), ("wrong_item", 3)]
WORD = re.compile(r"[a-z]{4,}")


def fetch(url: str, timeout: float = 30) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def sample(n: int, seed: int) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    ids = random.Random(seed).sample(range(1, LAST_BIN + 1), n)

    def one(i: int) -> bool:
        path = CACHE / f"{i}.json"
        if path.exists():
            return True
        data = fetch(f"{BASE}/metadata/{i}.json")
        if data:
            path.write_bytes(data)
        return bool(data)

    with ThreadPoolExecutor(16) as pool:
        got = sum(pool.map(one, ids))
    print(f"Metadata for {got} of {n} bins in {CACHE}")


def contents(meta: dict) -> dict[str, dict]:
    return {asin: {"name": (d.get("name") or "").strip(), "qty": int(d.get("quantity") or 0)}
            for asin, d in (meta.get("BIN_FCSKU_DATA") or {}).items()}


def usable(meta: dict) -> bool:
    c = contents(meta)
    total = sum(v["qty"] for v in c.values())
    return (1 <= len(c) <= 4 and 1 <= total <= 6 and total == meta.get("EXPECTED_QUANTITY")
            and all(v["name"] and v["qty"] >= 1 and ":" not in a and "," not in a for a, v in c.items()))


def words(name: str) -> set[str]:
    return set(WORD.findall(name.lower()))


def build(seed: int) -> None:
    metas = {}
    for path in sorted(CACHE.glob("*.json"), key=lambda p: int(p.stem)):
        try:
            metas[int(path.stem)] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
    names = {a: v["name"] for m in metas.values() for a, v in contents(m).items() if v["name"]}
    rng = random.Random(seed)
    pool = [i for i, m in sorted(metas.items()) if usable(m)]
    rng.shuffle(pool)
    print(f"{len(metas)} bins cached, {len(pool)} usable")

    manifest = (EVAL_DIR / "manifest.csv")
    if manifest.exists() and manifest.read_text(encoding="utf-8").count("\n") > 1:
        raise SystemExit("eval/manifest.csv already has boxes; move it away first.")

    rows, used_skus, taken = [], {}, set()

    def photo_ok(i: int) -> bytes | None:
        data = fetch(f"{BASE}/bin-images/{i}.jpg")
        if not data:
            return None
        w, h = Image.open(BytesIO(data)).size
        return data if min(w, h) >= MIN_SIDE else None

    def outside(c: dict[str, dict]) -> list[str]:
        """Products not in this bin, leaving out any with the same name as one in it (the same
        item under another ASIN): no photo could tell those apart."""
        same = {v["name"].lower() for v in c.values()}
        return sorted(a for a in names if a not in c and names[a].lower() not in same)

    def similar(c: dict[str, dict]) -> str:
        """A product from another bin, the most similar name first (a harder swap)."""
        here = set().union(*(words(v["name"]) for v in c.values()))
        others = outside(c)
        best = max(others, key=lambda a: (len(words(names[a]) & here), rng.random()))
        return best

    def plan(kind: str, c: dict[str, dict]) -> tuple[dict, str, str] | None:
        box = {a: v["qty"] for a, v in c.items()}
        if kind == "correct":
            return box, ("identical_multiples" if max(box.values()) >= 3 else "correct"), "Order matches the bin."
        if kind == "missing":
            add = rng.choice(outside(c))
            return {**box, add: 1}, kind, f"Order also asks for {add}, which isn't in the bin."
        if kind == "extra":
            if len(box) < 2:
                return None
            drop = rng.choice(sorted(box))
            return {a: n for a, n in box.items() if a != drop}, kind, f"Order leaves out {drop}, which is in the bin."
        if kind == "wrong_qty":
            a = rng.choice(sorted(box))
            n = box[a] + 1 if box[a] == 1 or rng.random() < 0.5 else box[a] - 1
            return {**box, a: n}, kind, f"Order says {n} x {a}; the bin has {box[a]}."
        if kind == "wrong_item":
            a = rng.choice(sorted(box))
            swap = similar(c)
            order = {(swap if k == a else k): n for k, n in box.items()}
            return order, kind, f"Order asks for {swap} instead of {a}, which is in the bin."
        raise ValueError(kind)

    boxes_dir = EVAL_DIR / "boxes"
    for split, mix, prefix in (("dev", DEV_MIX, "D"), ("test", TEST_MIX, "T")):
        kinds = [k for k, n in mix for _ in range(n)]
        rng.shuffle(kinds)
        for idx, kind in enumerate(kinds, 1):
            while True:
                if not pool:
                    raise SystemExit("Ran out of usable bins; run `sample` with a larger --n.")
                i = pool.pop()
                c = contents(metas[i])
                planned = plan(kind, c)
                if planned is None:
                    pool.insert(0, i)  # fine for another kind
                    continue
                data = photo_ok(i)
                if data:
                    break
            order, scenario, note = planned
            box_id = f"{prefix}{idx:02d}"
            (boxes_dir / box_id).mkdir(parents=True, exist_ok=True)
            (boxes_dir / box_id / "1.jpg").write_bytes(data)  # Amazon's file, unchanged
            taken.add(i)
            for a in set(order) | set(c):
                used_skus[a] = names[a]
            rows.append({"box_id": box_id, "split": split, "scenario": scenario,
                         "order_lines": ";".join(f"{a}:{n}" for a, n in order.items()),
                         "actual_contents": ";".join(f"{a}:{v['qty']}" for a, v in c.items()),
                         "conditions": "abid", "notes": f"ABID bin {i}. {note}"})
            print(f"{box_id} {scenario:20} bin {i}")

    # Decoys come from the same catalogue, so it holds a few more products than the boxes use.
    extra = [a for a in names if a not in used_skus]
    rng.shuffle(extra)
    for a in extra[:60]:
        used_skus[a] = names[a]
    items = [CatalogueItem(sku=a, asin=a, title=n[:120]) for a, n in sorted(used_skus.items())]
    folder = ROOT / "catalogue" / ORG
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "catalogue.json").write_text(
        Catalogue(organization_id=ORG, items=items).model_dump_json(indent=2), encoding="utf-8")

    import csv
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["box_id", "split", "scenario", "order_lines", "actual_contents", "conditions", "notes"])
        w.writeheader()
        w.writerows(rows)
    (HERE / "bins.json").write_text(json.dumps(
        {"seed": seed, "bins": {r["box_id"]: int(r["notes"].split()[2].rstrip(".")) for r in rows}},
        indent=2) + "\n", encoding="utf-8")
    (EVAL_DIR / "dataset.json").write_text(json.dumps({
        "name": "Amazon Bin Image Dataset (public, CC BY-NC-SA 3.0 US)",
        "source": "https://registry.opendata.aws/amazon-bin-imagery/",
        "org": ORG,
        "human_labels": False,
        "ground_truth": "each bin's contents as recorded by Amazon (the dataset's metadata), with the order "
                        "for each box written by eval/abid/build_abid.py from a fixed seed before any run",
        "note": ("Real warehouse bin photos, not our own shoot: the author had no products to photograph. "
                 "Ground truth is Amazon's record of each bin, not two human labellers. Photos are small "
                 "(the gate's minimum side is set to the camera's size before any run) and bins are "
                 "cluttered, so expect more UNCERTAIN than in a packing station."),
        "settings": {"min_side_px": MIN_SIDE, "blur_min_var": BLUR_MIN},
        "settings_why": ("Set for this camera from the dev photos alone, before any model run: minimum side "
                         "200 px (the shortest side across all 70 photos is 252 px); blur score 3.0 (all 20 dev "
                         "photos were readable by eye, the lowest scored 3.6; the phone setting is 60)."),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(rows)} boxes, {len(items)} catalogue products. Wrote eval/manifest.csv, eval/dataset.json, "
          f"eval/abid/bins.json, catalogue/{ORG}/catalogue.json and eval/boxes/.")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--n", type=int, default=2000)
    s.add_argument("--seed", type=int, default=2026)
    b = sub.add_parser("build")
    b.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    if args.cmd == "sample":
        sample(args.n, args.seed)
    else:
        build(args.seed)


if __name__ == "__main__":
    main()
