# Eval report: abid-test-v1

Held out: **yes**. frozen at 2026-09-30T14:49:44+00:00 in `eval/frozen-test.json` (settings, prompt, agent and eval code, manifest, box photos, catalogue files and reference photos hashed); the run matched it.

Dataset: **Amazon Bin Image Dataset (public, CC BY-NC-SA 3.0 US)**. Real warehouse bin photos, not our own shoot: the author had no products to photograph. Ground truth is Amazon's record of each bin, not two human labellers. Photos are small (the gate's minimum side is set to the camera's size before any run) and bins are cluttered, so expect more UNCERTAIN than in a packing station.

Split: **test** · boxes scored: **50** · model: `gemini-3.5-flash-lite` · order revealed to model: **False** · thresholds: match 0.7, visibility 0.7

## Box decision vs what was physically packed

| Measure | Result |
|---|---|
| **False SEAL** (wrong box would ship) | **2/26 (8%; 95% CI 2% to 24%)** of bad boxes |
| False STOP (good box stopped) | 12/24 (50%; 95% CI 31% to 69%) of good boxes |
| UNCERTAIN (sent to a human) | 18/50 (36%; 95% CI 24% to 50%) of all boxes |
| … on bad boxes / on good boxes | 11/26 (42%) / 7/24 (29%) |
| Bad boxes among the agent's SEALs | 2/7 (29%; 95% CI 8% to 64%) |
| Model failures ("Needs your decision") | 0 boxes, 0/50 (0%; 95% CI 0% to 7%) (target: 2% or less) |

| Truth \ Agent | SEAL | STOP_AND_FIX | UNCERTAIN | PENDING |
|---|---|---|---|---|
| SEAL | 5 | 12 | 7 | 0 |
| STOP_AND_FIX | 2 | 13 | 11 | 0 |

## Against the targets set before the eval

95% CI = Wilson score interval. "Met, not proven" means the rate is under the target but the sample is too small to rule out a rate above it.

| Measure | Result | Target | Kill if | Status |
|---|---|---|---|---|
| False SEAL (bad boxes sealed / bad boxes) | 2/26 (8%; 95% CI 2% to 24%) | 2% or less | > 5% while UNCERTAIN is 25% or lower | missed |
| False STOP (good boxes stopped / good boxes) | 12/24 (50%; 95% CI 31% to 69%) | 5% or less | > 15% | KILL |
| UNCERTAIN (sent to a hand check / all boxes) | 18/50 (36%; 95% CI 24% to 50%) | 25% or less | > 40% | missed |
| PENDING (model didn't answer / all boxes) | 0/50 (0%; 95% CI 0% to 7%) | 2% or less | > 5% | met, not proven (upper bound 7%) |

**Kill condition tripped:** False STOP (good boxes stopped / good boxes): 12/24 (50%), kill if > 15%. Per the one-pager, Pack Manager must not gate sealing; it runs only as an evidence recorder.

## Per check

FAIL means a problem is present. FN = a real problem the agent passed; FP = a false alarm.

| Check | n | Caught | Missed (FN) | False alarm (FP) | Uncertain on problem / on OK | Recall | Precision |
|---|---|---|---|---|---|---|---|
| all_items_present: line_present (per order line) | 106 | 3 | 2 | 16 | 8 / 35 | 0.6 | 0.158 |
| quantities_correct: line_quantity (per order line whose item is in the box) | 93 | 4 | 0 | 18 | 3 / 46 | 1.0 | 0.182 |
| unexpected_product: wrong_item or extra_item (per box) | 50 | 6 | 7 | 4 | 0 / 4 | 0.462 | 0.6 |

## Per scenario

| Scenario | n | Correct | Uncertain | False SEAL | False STOP |
|---|---|---|---|---|---|
| correct | 15 | 4 | 4 | 0 | 7 |
| extra | 6 | 4 | 1 | 1 | 0 |
| identical_multiples | 9 | 1 | 3 | 0 | 5 |
| missing | 6 | 2 | 4 | 0 | 0 |
| wrong_item | 7 | 3 | 3 | 1 | 0 |
| wrong_qty | 7 | 4 | 3 | 0 | 0 |

## Occlusion vs everything else

Boxes marked `hidden` in the manifest had an item under another item or filler when photographed.
One photo can't see those, so failures there are about geometry, not recognition.

| Group | n | Correct | Uncertain | False SEAL | False STOP |
|---|---|---|---|---|---|
This dataset doesn't record which items were hidden, so every box is in one group.
| Nothing hidden (recognition, count, photo quality) | 50 | 18 | 18 | 2 | 12 |

## Human labellers (from photos only, before the agent ran)

No human labellers for this dataset: each bin's contents as recorded by Amazon (the dataset's metadata), with the order for each box written by eval/abid/build_abid.py from a fixed seed before any run.

## Cost and speed

- Model latency p50 / p95: 4636 / 10405 ms
- Tokens per box (mean over the 50 boxes the model answered): 2439
- Cost per box (mean, paid-tier list price from .env): None
- Boxes with a photo failing the local quality gate: 0

## Every box the agent got wrong or sent to a human

| Box | Scenario | Conditions | Truth | Agent | Agent's first reason |
|---|---|---|---|---|---|
| T02 | missing | abid | STOP_AND_FIX | UNCERTAIN | ROBERTSON 3P20132 Fluorescent eBallast for 2 F40T12 Linear Lamps, Preheat- Rapid Start, 120Vac, 50-60Hz, Normal Ballast : 1 clearly counted, some units may be stacked or hidden; 6 ordered. |
| T03 | wrong_qty | abid | STOP_AND_FIX | UNCERTAIN | Dan Verssen Games -23 Field Commander - Rommel Deluxe: 1 clearly counted, some units may be stacked or hidden; 2 ordered. |
| T04 | correct | abid | SEAL | UNCERTAIN | School Smart Playground Ball - 8 1/2 inch - Red: 1 clearly counted, some units may be stacked or hidden; 1 ordered. |
| T06 | wrong_item | abid | STOP_AND_FIX | SEAL | Every ordered item is in the box in the right quantity, and nothing else is. |
| T07 | correct | abid | SEAL | STOP_AND_FIX | Not in the order: Lalawow PU Leather Backpack Fashion Daypack 14 inch Laptop Bags for College Boys Girls (Black) (#1). |
| T08 | identical_multiples | abid | SEAL | UNCERTAIN | 2 Pack Battery And Charger Kit For Nikon COOLPIX P900, P610, P600, B700 Digital Camera  Includes 2 Extended Replacement : 0 clearly counted, some units may be stacked or hidden; 3 ordered. |
| T10 | extra | abid | STOP_AND_FIX | SEAL | Every ordered item is in the box in the right quantity, and nothing else is. |
| T11 | wrong_qty | abid | STOP_AND_FIX | UNCERTAIN | S Super Stupid Soft Voodoo 165-170g: 0 clearly counted, some units may be stacked or hidden; 4 ordered. |
| T12 | wrong_item | abid | STOP_AND_FIX | UNCERTAIN | Story@Home Elegant Comfort Softest Bedding set, 3 Pcs set, Fancy Collection Flat (Full) Double Bed sheets With 2 Pillow : 0 clearly counted, some units may be stacked or hidden; 1 ordered. |
| T16 | wrong_qty | abid | STOP_AND_FIX | UNCERTAIN | Leg Avenue Women's Plus-Size Nylon Striped Tights, Black/Purple, 3X-4X: 1 clearly counted, some units may be stacked or hidden; 1 ordered. |
| T18 | correct | abid | SEAL | STOP_AND_FIX | Marvel Titan Hero Series Ant-Man: 0 in the box, 1 ordered. |
| T19 | identical_multiples | abid | SEAL | STOP_AND_FIX | Amos y Boris (Spanish Edition): 0 in the box, 1 ordered. |
| T21 | identical_multiples | abid | SEAL | STOP_AND_FIX | Kenu Airframe / Car Mount for Smartphones (Non Phablets) / Black: 2 in the box, 4 ordered. |
| T22 | correct | abid | SEAL | STOP_AND_FIX | NIVEA Kiss of Berry Swirl Vitamin Enriched Lip Care ( Pack of 6): 0 in the box, 1 ordered. |
| T24 | wrong_item | abid | STOP_AND_FIX | UNCERTAIN | Artempo DIY Guitar Pick Punch –Perfect Kit to Create Guitar Picks - Made of Heavy Duty Steel, 2 Plastic sheets Black and: 0 clearly counted, some units may be stacked or hidden; 1 ordered. |
| T25 | wrong_item | abid | STOP_AND_FIX | UNCERTAIN | Ted Baker London iPhone 5 iPhone 5S Leather Style Flip Case Cover Brown - Telegraph with Magnetic Closure - Lifetime Exc: 0 clearly counted, some units may be stacked or hidden; 1 ordered. |
| T26 | missing | abid | STOP_AND_FIX | UNCERTAIN | 2x Faster Charger 2.0 A Male to Micro B data sync BNU-137 2000mAH USB fast charging cable type Hi-Speed Compatible with : 0 clearly counted, some units may be stacked or hidden; 4 ordered. |
| T27 | correct | abid | SEAL | STOP_AND_FIX | Marvel Heroclix Nick Fury Agent Shield Booster Brick: 2 in the box, 1 ordered (1 too many). |
| T30 | identical_multiples | abid | SEAL | STOP_AND_FIX | Not in the order: KODAK Remanufactured Ink Cartridge Combo Pack Compatible With Canon PGI-220 (2945B004) High-Yield 3 Black Cartridges (#1). |
| T32 | identical_multiples | abid | SEAL | STOP_AND_FIX | VESA Mount Adapter Bracket for Samsung Monitors - fits many models including PX2370, S23C350H, S24B300EL, and more (2-pa: 2 in the box, 5 ordered. |
| T33 | correct | abid | SEAL | UNCERTAIN | unclear product #2: White bagged item. |
| T34 | correct | abid | SEAL | STOP_AND_FIX | GLS Audio 2ft Patch Cable Cords - XLR Male To RCA Color Cables - 2' Home Series Cord - 6 PACK: 0 in the box, 1 ordered. |
| T37 | correct | abid | SEAL | STOP_AND_FIX | Three Color Mix Cycling Bicycle Suit Bike Customized Ourdoor Wear For Men XXL Blue Yellow White (Jersey + Pants): 0 in the box, 1 ordered. |
| T38 | correct | abid | SEAL | STOP_AND_FIX | Not in the order: Nutrition: Food, Health, and Spiritual Development (#1). |
| T39 | identical_multiples | abid | SEAL | UNCERTAIN | unclear product #2: black item in packaging. |
| T40 | missing | abid | STOP_AND_FIX | UNCERTAIN | Outdoor Solar String Lights with dragonflies by Icicle, 16ft 20 LED 8 Modes Fairy Lighting for Christmas Trees, Garden, : 0 clearly counted, some units may be stacked or hidden; 2 ordered. |
| T42 | identical_multiples | abid | SEAL | UNCERTAIN | #2 may be YS Organic Bee Farms Certified Organic Raw Honey 100% Unprocessed, Unpasteurized - Kosher 32oz 2 Lbs Frustration Free Pa (confidence 0.60). |
| T44 | missing | abid | STOP_AND_FIX | UNCERTAIN | M80 Groove Massage Roller 15" (Black/Yellow): 1 clearly counted, some units may be stacked or hidden; 1 ordered. |
| T46 | correct | abid | SEAL | UNCERTAIN | Adagio Teas 16 oz. ingenuiTEA Bottom-Dispensing Teapot: 0 clearly counted, some units may be stacked or hidden; 1 ordered. |
| T48 | extra | abid | STOP_AND_FIX | UNCERTAIN | AmazonBasics Mini DisplayPort to HDMI Cable - 10 Feet: 0 clearly counted, some units may be stacked or hidden; 2 ordered. |
| T49 | identical_multiples | abid | SEAL | STOP_AND_FIX | Koomus Air Vent Universal Smartphone Car Mount Holder Cradle for all iPhone and Android devices - Retail Packaging - Bla: 0 in the box, 1 ordered. |
| T50 | correct | abid | SEAL | UNCERTAIN | Sunlite Thorn Resistant Schrader Valve Tube, 12-1/2 x 2-1/4" / 32mm, Black: 0 clearly counted, some units may be stacked or hidden; 1 ordered. |

Failure-mode names and notes go in EVAL.md after reviewing these rows and their photos.
