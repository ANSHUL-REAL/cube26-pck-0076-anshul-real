# Eval report: abid-test-oracle

Held out: **yes**. frozen at 2026-09-30T14:49:44+00:00 in `eval/frozen-test.json` (settings, prompt, agent and eval code, manifest, box photos, catalogue files and reference photos hashed); the run matched it.

Dataset: **Amazon Bin Image Dataset (public, CC BY-NC-SA 3.0 US)**. Real warehouse bin photos, not our own shoot: the author had no products to photograph. Ground truth is Amazon's record of each bin, not two human labellers. Photos are small (the gate's minimum side is set to the camera's size before any run) and bins are cluttered, so expect more UNCERTAIN than in a packing station.

Split: **test** · boxes scored: **50** · model: `none (oracle)` · order revealed to model: **False** · thresholds: match 0.7, visibility 0.7

**Oracle run: no model.** The agent was given exactly what the manifest says was packed, as a perfect object list. These numbers measure the decision rules alone, not the product.

## Box decision vs what was physically packed

| Measure | Result |
|---|---|
| **False SEAL** (wrong box would ship) | **0/26 (0%; 95% CI 0% to 13%)** of bad boxes |
| False STOP (good box stopped) | 0/24 (0%; 95% CI 0% to 14%) of good boxes |
| UNCERTAIN (sent to a human) | 0/50 (0%; 95% CI 0% to 7%) of all boxes |
| … on bad boxes / on good boxes | 0/26 (0%) / 0/24 (0%) |
| Bad boxes among the agent's SEALs | 0/24 (0%; 95% CI 0% to 14%) |
| Model failures ("Needs your decision") | 0 boxes, 0/50 (0%; 95% CI 0% to 7%) (target: 2% or less) |

| Truth \ Agent | SEAL | STOP_AND_FIX | UNCERTAIN | PENDING |
|---|---|---|---|---|
| SEAL | 24 | 0 | 0 | 0 |
| STOP_AND_FIX | 0 | 26 | 0 | 0 |

## Against the targets set before the eval

95% CI = Wilson score interval. "Met, not proven" means the rate is under the target but the sample is too small to rule out a rate above it.

| Measure | Result | Target | Kill if | Status |
|---|---|---|---|---|
| False SEAL (bad boxes sealed / bad boxes) | 0/26 (0%; 95% CI 0% to 13%) | 2% or less | > 5% while UNCERTAIN is 25% or lower | met, not proven (upper bound 13%) |
| False STOP (good boxes stopped / good boxes) | 0/24 (0%; 95% CI 0% to 14%) | 5% or less | > 15% | met, not proven (upper bound 14%) |
| UNCERTAIN (sent to a hand check / all boxes) | 0/50 (0%; 95% CI 0% to 7%) | 25% or less | > 40% | met |
| PENDING (model didn't answer / all boxes) | 0/50 (0%; 95% CI 0% to 7%) | 2% or less | > 5% | met, not proven (upper bound 7%) |

No kill condition tripped.

## Per check

FAIL means a problem is present. FN = a real problem the agent passed; FP = a false alarm.

| Check | n | Caught | Missed (FN) | False alarm (FP) | Uncertain on problem / on OK | Recall | Precision |
|---|---|---|---|---|---|---|---|
| all_items_present: line_present (per order line) | 106 | 13 | 0 | 0 | 0 / 0 | 1.0 | 1.0 |
| quantities_correct: line_quantity (per order line whose item is in the box) | 93 | 7 | 0 | 0 | 0 / 0 | 1.0 | 1.0 |
| unexpected_product: wrong_item or extra_item (per box) | 50 | 13 | 0 | 0 | 0 / 0 | 1.0 | 1.0 |

## Per scenario

| Scenario | n | Correct | Uncertain | False SEAL | False STOP |
|---|---|---|---|---|---|
| correct | 15 | 15 | 0 | 0 | 0 |
| extra | 6 | 6 | 0 | 0 | 0 |
| identical_multiples | 9 | 9 | 0 | 0 | 0 |
| missing | 6 | 6 | 0 | 0 | 0 |
| wrong_item | 7 | 7 | 0 | 0 | 0 |
| wrong_qty | 7 | 7 | 0 | 0 | 0 |

## Occlusion vs everything else

Boxes marked `hidden` in the manifest had an item under another item or filler when photographed.
One photo can't see those, so failures there are about geometry, not recognition.

| Group | n | Correct | Uncertain | False SEAL | False STOP |
|---|---|---|---|---|---|
This dataset doesn't record which items were hidden, so every box is in one group.
| Nothing hidden (recognition, count, photo quality) | 50 | 50 | 0 | 0 | 0 |

## Human labellers (from photos only, before the agent ran)

No human labellers for this dataset: each bin's contents as recorded by Amazon (the dataset's metadata), with the order for each box written by eval/abid/build_abid.py from a fixed seed before any run.

## Cost and speed

- Model latency p50 / p95: None / None ms
- Tokens per box (mean over the 0 boxes the model answered): None
- Cost per box (mean, paid-tier list price from .env): None
- Boxes with a photo failing the local quality gate: 0

## Every box the agent got wrong or sent to a human

| Box | Scenario | Conditions | Truth | Agent | Agent's first reason |
|---|---|---|---|---|---|

Failure-mode names and notes go in EVAL.md after reviewing these rows and their photos.
