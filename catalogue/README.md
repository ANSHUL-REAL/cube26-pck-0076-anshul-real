# Catalogue

What the agent knows about each product. The vision model gets these descriptions and reference photos for the ordered products, their look-alikes and a couple of decoys (never the quantities).

| Folder | What |
|---|---|
| `sample/` | The organisers' 10 synthetic SKUs (text only, from `receiving_sample.csv`). Used to replay `data/pack_sample.csv` and as demo orders |
| `<organization_id>/` | An organisation's own products: `catalogue.json`, `images/<SKU>/1.jpg…`, and optionally `orders.json` (demo orders loaded by `python -m app.migrate`) |
| `_template/` | A starting point to copy |

An organisation's catalogue is merged with `sample/`, and its own entries win.

## Writing a product entry

| Field | Why it matters |
|---|---|
| `sku` | Key for everything. Use the seller's SKU, not the ASIN (sample data has one ASIN on two products) |
| `title`, `attributes` | Shown to the operator and to the model |
| `sellable_unit` | What **one** ordered unit looks like. For multipacks say so: "one box holding 2 mugs; the box counts as ONE unit" |
| `distinguishing_features` | The detail that separates it from its look-alikes (colour, size print, flavour label) |
| `confusable_with` | Look-alike SKUs. They are always shown to the model next to this one |
| `component_lookalikes` | SKUs that look like a part shipped inside this product (a lamp's USB cable vs the cable sold alone). A loose one becomes "check by hand" instead of "extra" |
| `reference_images` | 2–3 photos on a plain background, paths relative to the org folder |
| `allowed_inserts` (top level) | Packing material and paperwork that is never an "extra item" |
