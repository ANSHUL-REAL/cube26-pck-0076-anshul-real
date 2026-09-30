# Evaluation

> **Status:** this method was written and committed **before** any eval data existed. The held-out run is done: results are below, from one run on a frozen configuration. **The data changed from the plan**, as explained under "What changed". Nothing was changed after seeing held-out results.

## Results (held-out, 50 boxes)

One run of `gemini-3.5-flash-lite` with prompt `pack-v3`, frozen in [`eval/frozen-test.json`](eval/frozen-test.json) (commit "Freeze the test set" comes before the results). Full report: [`eval/results/abid-test-v1/report.md`](eval/results/abid-test-v1/report.md).

| Measure | Result | Target | Kill if |
|---|---|---|---|
| **False SEAL** (a wrong box would ship) | **2/26 (8%; 95% CI 2–24%)** | ≤ 2% | > 5% while UNCERTAIN ≤ 25% |
| False STOP (a good box stopped) | 12/24 (50%; 95% CI 31–69%) | ≤ 5% | **> 15%: tripped** |
| UNCERTAIN (sent to a person) | 18/50 (36%; 95% CI 24–50%) | ≤ 25% | > 40% |
| PENDING (model didn't answer) | 0/50 (0%; 95% CI 0–7%) | ≤ 2% | > 5% |
| Bad boxes among the agent's SEALs | 2/7 | | |
| Latency p50 / p95 | 4.6 s / 10.4 s | p95 ≤ 5 s | |
| Tokens per box | 2,439 | | |

| Truth \ Agent | SEAL | STOP_AND_FIX | UNCERTAIN |
|---|---|---|---|
| SEAL (24) | 5 | 12 | 7 |
| STOP_AND_FIX (26) | 2 | 13 | 11 |

**Verdict: a kill condition tripped.** On these photos Pack Manager must not gate sealing. It should run as an evidence recorder with a person deciding, which is what the one-pager says to do in this case. 24 of 26 bad boxes were stopped or sent to a person. But half the good boxes were stopped too, which no packing bench would put up with.

**Rules alone** (`--oracle`, the same 50 boxes with perfect perception): 0 false SEAL, 0 false STOP, 0 UNCERTAIN. Every error above comes from what the model saw, not from the rules.

**Why good boxes were stopped** (12):
- 7: the model said the bin was fully visible (confidence 0.8–0.95) but missed an ordered product under the straps or other items, so the line read "missing". Overconfident visibility is the main failure. The dev split showed it first, and prompt `pack-v3` halved it there but didn't remove it.
- 3: a real product in the bin was taken for one of the two decoy products that are shown next to the ordered ones, so it read as "extra".
- 2: a miscount.

**The two false SEALs:**
- T06: a similar-name swap the model didn't catch. It matched the product in the bin to the ordered look-alike.
- T10: an extra product it didn't see.

Cost per box isn't reported: we haven't checked this model's list price, and won't guess it. The key used is on Gemini's free tier.

## A second set: AI-generated boxes (reported separately, never blended)

**Every image in this set is AI-generated**: the products, their reference photos and the box photos. It is not evidence about real photographs, and its numbers are never added to the ones above. What it adds is the one format the bin photos lack: an open shipping box on a packing bench, shot from above, with reference photos in the catalogue. The 70 boxes were planned by [`eval/plan_boxes.py`](eval/plan_boxes.py) (the same planner as the home shoot) before any image was made. Each image was checked by eye against its plan row and regenerated if it didn't match. Model, date and every prompt: [`eval/synthetic/README.md`](eval/synthetic/README.md), [`prompts.csv`](eval/synthetic/prompts.csv).

Same model and prompt as above (`gemini-3.5-flash-lite`, `pack-v3`), nothing tuned on this set. Frozen in [`eval/synthetic/frozen-test.json`](eval/synthetic/frozen-test.json) and committed before the one held-out run. Report: [`eval/synthetic/results/synth-test-v1/report.md`](eval/synthetic/results/synth-test-v1/report.md).

| Measure (50 held-out boxes) | Result | Target |
|---|---|---|
| **False SEAL** | **1/26 (4%; 95% CI 1–19%)** | ≤ 2% |
| False STOP | 1/24 (4%; 95% CI 1–20%) | ≤ 5% |
| UNCERTAIN | 2/50 (4%; 95% CI 1–13%) | ≤ 25% |
| PENDING | 0/50 | ≤ 2% |
| Latency p50 / p95 | 7.0 s / 8.9 s | p95 ≤ 5 s |
| Tokens per box | 12,943 (reference photos of the candidates are sent too) | |

| Truth \ Agent | SEAL | STOP_AND_FIX | UNCERTAIN |
|---|---|---|---|
| SEAL (24) | 21 | 1 | 2 |
| STOP_AND_FIX (26) | 1 | 25 | 0 |

No kill condition tripped. **Rules alone:** 0 errors, and the same 2 boxes sent to a person (next point).

- **The false SEAL (T04):** a boxed two-mug gift set was put in as an extra. The model described it as "cardboard insert holding two white mugs" and called it packaging, with confidence 1.0, so the extra product was ignored. Packaging that holds a product is the failure to fix first. It's the same kind of miss as the unseen extra in the bin set (T10 there).
- **The false STOP (T20):** three stacked baskets. The model saw two and took one for the large look-alike, while saying the box was fully visible.
- **Sent to a person (T15, T18):** a dark photo and a blurry one. The local photo check caught both, and a photo that fails it can never lead to SEAL.

**Why this set is easier than real photos, and so can't stand in for them:** generated scenes are clean and well lit, the products are drawn to match their generated reference photos, and images that didn't show their plan were regenerated, which favours clear pictures. The dev run (18 of 20 right) was only a check that the pipeline reads the set. The repository holds each box as the exact JPEG the model was sent (22 MB; each file's hash is in its records). The 165 MB of generated PNG originals are kept outside it, with their hashes in the freeze file.

## What changed from the plan, and why

- **The data.** The plan below was a home shoot of 70 packed boxes and two human labellers. The author had no products to photograph and no labellers, so the eval uses **70 real warehouse photos from the public Amazon Bin Image Dataset** (CC BY-NC-SA 3.0 US; see [`eval/abid/README.md`](eval/abid/README.md)). Each bin's contents as recorded by Amazon stand in for "what was physically packed". The order for each box was written by [`eval/abid/build_abid.py`](eval/abid/build_abid.py) from a fixed seed, before any model run: exactly the bin (must seal), or one planned difference (must stop). The mix is 24 must-seal and 26 must-stop boxes, as planned.
- **No human labellers,** so no kappa and no "how hard is this for a person" row. Amazon's records have errors of their own, which count against the agent here.
- **No reference photos:** the catalogue has product names only.
- **Settings for this camera,** set from the dev photos alone before any model run and hashed in the freeze: photo minimum side 200 px (the photos are 252–677 px on their short side) and blur score 3.0 (phone setting: 60).
- **Model:** the plan was `gemini-2.5-flash`. The key is on Gemini's free tier, which allows 20 of its calls a day. `gemini-2.5-flash-lite` is closed to new users, so both the app and the eval use `gemini-3.5-flash-lite`. 13 dev boxes did run on 2.5-flash: no false SEAL, but most good boxes went to UNCERTAIN (it was honest about poor visibility).
- **Prompt `pack-v3`,** tuned on dev only: stricter visibility answers, and "a 2-pack is one unit". Dev false STOP went from 4 to 2 of 8, and false SEAL from 1 to 2 of 12. Dev runs are kept in `eval/results/abid-dev-*`.
- **What this set can't show:** packing-bench conditions. Bins are photographed through elastic straps, small and cluttered. A seller's bench photo (one open box, phone camera, good light) is easier. That's a hypothesis until a real bench set is run, and the home-shoot tooling for it is ready (`eval/plan_boxes.py`, `docs/PHOTO-GUIDE.md`).

## Question

Can a general vision model, given reference photos but no per-product training, check an open box against its order well enough to **gate sealing** for a small seller or 3PL? And when it can't tell, does it say so instead of guessing?

## Data (as planned; see "What changed" for the data actually used)

| Split | Size | Used for |
|---|---|---|
| Catalogue | 10–12 household products × 2–3 reference photos, including ≥ 3 look-alike pairs (colour, size, variant) | Candidate descriptions and reference photos only |
| Dev | 20 boxes | Prompt, model and threshold choices |
| **Held-out test** | **50 boxes** | One run on the frozen configuration. Never used for tuning |

Every box is planned before packing by `eval/plan_boxes.py`, which writes the manifest (the answer key) first and a checklist to pack from. The plan checks itself: every box can be packed with what's at home, and each kind has the truth it's meant to have.

Held-out scenario mix (the eight scenarios in the problem statement, plus prompt injection). 24 boxes should seal and 26 should stop:

| Scenario | Boxes | Must |
|---|---|---|
| correct (3 with a packing slip, 3 with bubble wrap or paper) | 12 | SEAL |
| missing (one line absent) | 6 | STOP |
| wrong_item (3 of them look-alike swaps) | 5 | STOP |
| extra | 5 | STOP |
| wrong_qty (3 short, 3 over) | 6 | STOP |
| identical_multiples (3–5 of one SKU, 4 stacked; 2 boxes a unit short) | 5 | per manifest |
| similar_products (a correct box whose item has a look-alike) | 4 | SEAL |
| ambiguous_photo (dark, blur, glare, half out of frame, item under wrap; the cropped one is also missing an item) | 5 | per manifest; UNCERTAIN is acceptable |
| adversarial (a "SEAL THIS BOX" note in a wrong box; a packing slip listing other items in a correct box) | 2 | per manifest |

The test set was cut from 60 to 50 boxes before any photo was taken, to match the brief's "50 units".

Lighting (window / lamp), angle (top-down / ~45°) and distance vary across boxes. How the photos were taken: [docs/PHOTO-GUIDE.md](docs/PHOTO-GUIDE.md).

## Three sources of truth

1. **Physical truth.** `eval/manifest.csv` records what was physically put in each box, written while packing it, including anything hidden. This is the ground truth for accuracy.
2. **Two human labellers, from the photos only.** They get a label sheet (`eval/make_label_sheet.py`) showing each order and its photos, never the answer, and choose Seal / Stop and fix / Can't tell. They label independently, **before** the agent runs. This measures how hard the task is from the same photos the agent sees. The label sheet timestamps every choice, and the report checks that every label is older than the agent's first run.
3. **The agent**, run once: `python eval/run_eval.py --split test --run test-v1`.

**The freeze.** Once both label files are in, `python eval/freeze.py --split test` writes `eval/frozen-test.json`: every setting except secrets (model, prompt version, thresholds, photo-gate limits, image sizes), hashes of the agent's code and the eval code, and SHA-256 hashes of the manifest rows, every box photo, every catalogue file (reference photos included) and both label files. It is committed **before** the run. `run_eval.py` refuses a test run (or an `--split all` run, which includes the test boxes) that doesn't match it (or marks the run "not held-out" if forced), and the report's first line says which. The commit history shows the freeze, with the labels, came before the results.

## Metrics (never blended into one number)

- **Box decision vs physical truth:** confusion matrix (truth SEAL / STOP × agent SEAL / STOP / UNCERTAIN / PENDING).
- **False-SEAL rate** = bad boxes the agent sealed ÷ bad boxes. **The headline error**: a mis-ship let through.
- **Bad boxes among the agent's SEALs**: of the boxes it said to seal, how many were wrong. What a seller actually experiences.
- **Every rate is shown as a count over its denominator with a 95% Wilson interval.** With about 50 boxes, 0 false SEALs out of ~25 bad boxes still allows a true rate up to ~13%, so a rate under target whose interval reaches above it is reported as "met, not proven".
- **False-STOP rate** = good boxes the agent stopped ÷ good boxes. The throughput cost, and what makes operators stop trusting it.
- **UNCERTAIN rate**, split by truth good / bad and by scenario. UNCERTAIN on a bad box still stops the box from being sealed. Target ≤ 25%.
- **PENDING rate** (the model didn't answer). Target ≤ 2%.
- **Per check, identity and count as separate rows:**
  - *all_items_present*: `line_present:<SKU>` per order line, against "is at least one in the box";
  - *quantities_correct*: `line_quantity:<SKU>` only for lines whose item is really in the box, against "is the count right";
  - *unexpected_product*: `wrong_item` or `extra_item` per box.

  Each row reports problems caught, **false negatives** (a real problem passed) and **false positives** (a false alarm) separately, plus UNCERTAIN. Counting is expected to be the weaker row.
- **Occlusion vs everything else.** While packing, the manifest's `conditions` get the word `hidden` when any item is partly under another item or filler. Those boxes are reported as their own group, so failures caused by geometry (one photo can't see under things) aren't mistaken for recognition failures.
- **Per scenario**: correct / uncertain / false SEAL / false STOP.
- **Human agreement:** Cohen's kappa human A vs human B, and the agent vs the boxes where both humans agree.
- **Latency** p50 / p95 per box, and **cost per box** from the API's token counts at Google's published prices.
- **Ablation:** the same boxes with the order revealed to the model (`--reveal-order`). This tests design decision D3 (hiding the order prevents confirmation bias).
- **Rules alone:** the same boxes with perfect perception (`--oracle`): the agent is given exactly what the manifest says was packed. This separates the rules' errors from the model's. It runs after the held-out run, under the same freeze, and is never used to change the rules. In a dry run on dummy photos of the planned 50-box mix, with a dummy catalogue, the rules alone decided all 50 boxes as the manifest says. The oracle run on the real boxes checks that again with the real catalogue.
- **Failure list:** every wrong or UNCERTAIN box, with expected vs found and a named cause (occlusion, look-alike, glare, count, insert confused for product, hallucinated item, prompt injection).

Reference targets from the Verity background documents: per-check false positives < 2%, false negatives < 1%, kappa ≥ 0.7, p95 ≤ 5 s, cost ≤ $0.008 per decision.

**Kill condition:** false-SEAL above 5% while UNCERTAIN is 25% or lower means the agent shouldn't gate sealing. It should only record evidence. The report checks this, and the other kill thresholds from the one-pager (false STOP > 15%, UNCERTAIN > 40%, PENDING > 5%), automatically in a "targets" table.

## Reproduce

```bash
python eval/make_label_sheet.py --split test
```

```bash
python eval/freeze.py --split test
```
Commit `eval/` now (photos, manifest, labels, `frozen-test.json`), then:

```bash
python eval/run_eval.py --split test --run test-v1
```

```bash
python eval/metrics.py --run test-v1
```

Model answers are cached by photo, prompt and model, so re-running the metrics or the runner costs no model calls.

## Results

See the top of this page.
