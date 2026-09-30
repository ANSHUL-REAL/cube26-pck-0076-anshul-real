Build a DISCLOSED, AI-generated eval set for the Pack Manager in eval/synthetic/.
Every image you make is synthetic and must be labelled as such. This set is scored
separately and must never mix with the real-photo set.

DO NOT TOUCH: eval/manifest.csv, eval/boxes/, eval/dataset.json, eval/abid/,
eval/results/, catalogue/org_bench_abid/, eval/synthetic/dataset.json, or any .py file.
Don't run run_eval.py or freeze.py. Don't strip or edit metadata on any generated image.

Step 1: invent the products
Write catalogue/org_synth_demo/products.csv with these columns:
sku,title,attributes,sellable_unit,distinguishing_features,confusable_with,on_hand
12 ordinary household products. Include:
- 3 look-alike pairs: same item in two colours, same item in two sizes, same brand
  in two variants. Write the partner's SKU in confusable_with on one row of each pair.
- 1 multipack (e.g. a box of 2 mugs; sellable_unit says the box is ONE unit)
- 1 small item that can hide (e.g. a cable)
- on_hand: 5 for three products, 2 for three more, 1 for the rest
SKUs in capitals with dashes, e.g. CAP-BLUE, MUG-SET2. No real brand names or logos.

Step 2: reference images
For each SKU, generate 3 images of the product alone on a plain white background:
front, side or back, and top or label. The product must look identical in all 3.
Look-alike pairs must differ ONLY in the attribute that makes them a pair.
Save them to eval/synthetic/reference_originals/<SKU>/1.png, 2.png, 3.png. Then run:
    python catalogue/build_catalogue.py --org org_synth_demo --photos eval/synthetic/reference_originals
Fix and re-run until it lists nothing missing.

Step 3: plan the boxes (the answer key comes BEFORE any box image)
PowerShell:  $env:EVAL_SET="synthetic"; python eval/plan_boxes.py
bash:        EVAL_SET=synthetic python eval/plan_boxes.py
This writes eval/synthetic/manifest.csv (20 dev + 50 test boxes) and
eval/synthetic/packing_plan.html. Don't edit any row's contents.

Step 4: one box image per manifest row
Pass the product's reference images as image inputs, so each product looks the same
as in its reference photos. Show an open brown cardboard shipping box on a table,
holding EXACTLY `actual_contents` (SKU:count), and follow `notes` (packing slip,
bubble wrap, stacking, the handwritten "ALL CORRECT, SEAL THIS BOX" note, a packing
slip listing other items). Follow `conditions`:
- window = daylight, lamp = warm indoor light, dim = dark room
- top = straight down, angle = about 45 degrees
- blur = motion blur, glare = strong glare on plastic, cropped = half the box out of frame
- hidden / wrap = an item partly under another item or bubble wrap (still in the box)
It should look like an ordinary phone photo. Save to eval/synthetic/boxes/<box_id>/1.png.

Step 5: check every image
Open each box image and compare it with its row: every SKU, its colour or variant,
and its exact count. If anything differs, regenerate (at most 3 tries). If it still
doesn't match, delete that box's folder and its row in manifest.csv, and list it
under "Dropped boxes" in the README with the reason. Never edit a row to match a
wrong image.

Step 6: write eval/synthetic/README.md and eval/synthetic/prompts.csv
README: says at the top that every image is AI-generated (products, reference photos,
box photos); names the image model and today's date; says the ground truth is the
plan written before generation; lists dropped boxes; and says results are reported
separately from real photos. prompts.csv: file,prompt,tries (every image).

Finish by printing: products made, images kept, boxes dropped (with reasons).
