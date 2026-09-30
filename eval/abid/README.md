# Eval set: Amazon Bin Image Dataset (public)

The photos in `eval/boxes/` are from the **Amazon Bin Image Dataset** (ABID), published by Amazon on the Registry of Open Data on AWS: <https://registry.opendata.aws/amazon-bin-imagery/>. They are used here under its licence, **Creative Commons Attribution-NonCommercial-ShareAlike 3.0 United States** (CC BY-NC-SA 3.0 US), unchanged, for a non-commercial buildathon entry. The same licence applies to these photos in this repository.

## Why this set

The plan was a home shoot of 70 packed boxes, labelled by two people (see `docs/PHOTO-GUIDE.md` and `eval/plan_boxes.py`; that tooling still works). The author had no products to photograph and no labellers, so the eval uses this public set instead. We say so plainly in EVAL.md and the README.

## How the boxes were made

`python eval/abid/build_abid.py sample` downloads the metadata of 2,000 random bins. `build` (seed 7) then keeps bins with 1–4 products and 1–6 units whose record adds up, and writes an order for each box **before any model run**:

| Kind | The order | Must |
|---|---|---|
| correct / identical_multiples | exactly the bin's record | SEAL |
| missing | the record plus a product from another bin | STOP |
| extra | the record minus one of its products | STOP |
| wrong_qty | one quantity off by one | STOP |
| wrong_item | one product swapped for another bin's, the most similar name available | STOP |

Held-out test: 50 boxes (24 must seal, 26 must stop). Dev: 20 boxes. `bins.json` lists which bin each box came from. `eval/dataset.json` records the source, that there are no human labellers, and the two settings fixed for this camera from the dev photos (photo minimum side and blur score).

## What this set can and can't show

- **Real photos, real products, real clutter.** Bins are photographed from above through elastic straps, often with products stacked or in plastic. That's harder than a packing bench.
- **Ground truth is Amazon's record**, not two human labellers. It has errors of its own, which count against the agent here.
- **The catalogue has product names only**, no reference photos.
- The photos are small (the shortest side is 252–677 px).
