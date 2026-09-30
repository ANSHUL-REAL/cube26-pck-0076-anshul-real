# Eval report: synth-test-v1

Held out: **yes**. frozen at 2026-09-30T16:12:51+00:00 in `eval/synthetic/frozen-test.json` (settings, prompt, agent and eval code, manifest, box photos, catalogue files and reference photos hashed); the run matched it.

Dataset: **Synthetic boxes (AI-generated images, not photographs)**. Every product, reference photo and box photo in this set is AI-generated. It tests the agent on scenarios planned in advance, at no packing cost; it does not show how the agent does on real photographs. Results are reported separately from every real-photo set and are never blended with them.

Split: **test** · boxes scored: **50** · model: `gemini-3.5-flash-lite` · order revealed to model: **False** · thresholds: match 0.7, visibility 0.7

## Box decision vs what was physically packed

| Measure | Result |
|---|---|
| **False SEAL** (wrong box would ship) | **1/26 (4%; 95% CI 1% to 19%)** of bad boxes |
| False STOP (good box stopped) | 1/24 (4%; 95% CI 1% to 20%) of good boxes |
| UNCERTAIN (sent to a human) | 2/50 (4%; 95% CI 1% to 13%) of all boxes |
| … on bad boxes / on good boxes | 0/26 (0%) / 2/24 (8%) |
| Bad boxes among the agent's SEALs | 1/22 (5%; 95% CI 1% to 22%) |
| Model failures ("Needs your decision") | 0 boxes, 0/50 (0%; 95% CI 0% to 7%) (target: 2% or less) |

| Truth \ Agent | SEAL | STOP_AND_FIX | UNCERTAIN | PENDING |
|---|---|---|---|---|
| SEAL | 21 | 1 | 2 | 0 |
| STOP_AND_FIX | 1 | 25 | 0 | 0 |

## Against the targets set before the eval

95% CI = Wilson score interval. "Met, not proven" means the rate is under the target but the sample is too small to rule out a rate above it.

| Measure | Result | Target | Kill if | Status |
|---|---|---|---|---|
| False SEAL (bad boxes sealed / bad boxes) | 1/26 (4%; 95% CI 1% to 19%) | 2% or less | > 5% while UNCERTAIN is 25% or lower | missed |
| False STOP (good boxes stopped / good boxes) | 1/24 (4%; 95% CI 1% to 20%) | 5% or less | > 15% | met, not proven (upper bound 20%) |
| UNCERTAIN (sent to a hand check / all boxes) | 2/50 (4%; 95% CI 1% to 13%) | 25% or less | > 40% | met |
| PENDING (model didn't answer / all boxes) | 0/50 (0%; 95% CI 0% to 7%) | 2% or less | > 5% | met, not proven (upper bound 7%) |

No kill condition tripped.

## Per check

FAIL means a problem is present. FN = a real problem the agent passed; FP = a false alarm.

| Check | n | Caught | Missed (FN) | False alarm (FP) | Uncertain on problem / on OK | Recall | Precision |
|---|---|---|---|---|---|---|---|
| all_items_present: line_present (per order line) | 83 | 12 | 0 | 1 | 1 / 0 | 1.0 | 0.923 |
| quantities_correct: line_quantity (per order line whose item is in the box) | 70 | 8 | 0 | 2 | 0 / 0 | 1.0 | 0.8 |
| unexpected_product: wrong_item or extra_item (per box) | 50 | 10 | 1 | 3 | 0 / 0 | 0.909 | 0.769 |

## Per scenario

| Scenario | n | Correct | Uncertain | False SEAL | False STOP |
|---|---|---|---|---|---|
| adversarial | 2 | 2 | 0 | 0 | 0 |
| ambiguous_photo | 5 | 3 | 2 | 0 | 0 |
| correct | 12 | 12 | 0 | 0 | 0 |
| extra | 5 | 4 | 0 | 1 | 0 |
| identical_multiples | 5 | 4 | 0 | 0 | 1 |
| missing | 6 | 6 | 0 | 0 | 0 |
| similar_products | 4 | 4 | 0 | 0 | 0 |
| wrong_item | 5 | 5 | 0 | 0 | 0 |
| wrong_qty | 6 | 6 | 0 | 0 | 0 |

## Occlusion vs everything else

Boxes marked `hidden` in the manifest had an item under another item or filler when photographed.
One photo can't see those, so failures there are about geometry, not recognition.

| Group | n | Correct | Uncertain | False SEAL | False STOP |
|---|---|---|---|---|---|
| Items hidden (occlusion) | 5 | 4 | 0 | 0 | 1 |
| Nothing hidden (recognition, count, photo quality) | 45 | 42 | 2 | 1 | 0 |

## Human labellers (from photos only, before the agent ran)

No human labellers for this dataset: eval/synthetic/manifest.csv, planned by eval/plan_boxes.py before any image was generated; each image was checked by eye against its row and regenerated or dropped when it didn't match.

## Cost and speed

- Model latency p50 / p95: 7005 / 8877 ms
- Tokens per box (mean over the 50 boxes the model answered): 12943
- Cost per box (mean, paid-tier list price from .env): None
- Boxes with a photo failing the local quality gate: 2

## Every box the agent got wrong or sent to a human

| Box | Scenario | Conditions | Truth | Agent | Agent's first reason |
|---|---|---|---|---|---|
| T04 | extra | lamp;angle | STOP_AND_FIX | SEAL | Every ordered item is in the box in the right quantity, and nothing else is. |
| T15 | ambiguous_photo | dim;angle;dark | SEAL | UNCERTAIN | Photo 1: Photo is too dark. Add light or move closer to a window. The operator chose to continue. |
| T18 | ambiguous_photo | lamp;top;blur | SEAL | UNCERTAIN | Photo 1: Photo looks blurry. Hold the phone steady and tap to focus. The operator chose to continue. |
| T20 | identical_multiples | lamp;angle;hidden | SEAL | STOP_AND_FIX | Expected Rectangular woven storage basket, found Rectangular woven storage basket (#1). |

Failure-mode names and notes go in EVAL.md after reviewing these rows and their photos.
