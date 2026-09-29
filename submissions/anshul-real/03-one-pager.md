# One-pager

**Problem.** Merchant-fulfilled sellers and small 3PLs mis-ship: missing items, wrong colour or size, wrong quantity, extras. Each one costs a refund, a return, a reshipment and often a review. Nobody checks, because checking every box by hand costs more than the mis-ships. When a buyer disputes, the seller has no proof of what was sent.

**Customer.** A seller or 3PL packing its own orders at tables, with phones and no camera station. Not fully FBA sellers.

**Solution.** Photograph the open box. One vision-model call lists what's in it, without being told the order. Deterministic rules compare that with the order and return **Seal**, **Stop and fix** (exact fixes) or **Check by hand** (what would settle it). Every box gets an evidence record with photos, checks, the decision, overrides and a content hash. The Returns and Recovery tracks can read it.

**Why now / why this way.** General vision models can compare an open box against reference photos without per-product training. The known order turns open-ended recognition into checking against a list, plus spotting anything that doesn't belong.

## Metrics

Measured on a held-out set of real boxes against what was physically packed. Every error type is reported separately.

| Metric | Why it matters | Target | Kill if |
|---|---|---|---|
| **False-SEAL rate** (bad boxes sealed ÷ bad boxes) | A mis-ship let through; the error that costs money | ≤ 2% | **> 5% while UNCERTAIN ≤ 25%** |
| False-STOP rate (good boxes stopped ÷ good boxes) | Slows the line; operators stop trusting it | ≤ 5% | > 15% |
| UNCERTAIN rate ("Check by hand") | Every one interrupts a person; a correct agent that sends 20% of boxes to a hand check still fails commercially | ≤ 25% | > 40% |
| PENDING rate ("Needs your decision": the model didn't answer) | Above a few percent, packers learn to ignore it even when it works | ≤ 2% | > 5% |
| Items present (`line_present`, per order line) | Is each ordered SKU in the box at all | FN < 1%, FP < 2% | — |
| Counts correct (`line_quantity`, per line whose item is in the box) | Counting overlapping units is much harder than finding a SKU; expected to be the weaker row | FN < 1%, FP < 2% | — |
| Wrong or extra item (per box) | Look-alikes and strays | FN < 1%, FP < 2% | — |
| Human-vs-human kappa (2 labellers, photos only) | How hard the task is from a photo | reported | — |
| Agent vs human consensus kappa | Is the agent as good as a careful person | ≥ 0.7 | — |
| p95 latency per box | "Don't slow my line down" | ≤ 5 s | > 10 s |
| Cost per box | Pack touches every order | ≤ $0.008 | > $0.02 |

## Kill condition

If the held-out false-SEAL rate is **above 5% while UNCERTAIN is 25% or lower**, Pack Manager must not gate sealing. It runs only as an evidence recorder: photo plus record, no verdict. That alone still answers "what did you send?".

These targets were written before any real box was photographed.

## Design choices that shape the numbers

- **Occlusion: one shot, reported separately.** The packer takes one photo of the finished, open box (up to 3 if items are stacked). We don't ask for a photo per layer, because it costs throughput and throughput is what packers are measured on. A single photo can't see an item under another item, so when the model reports that items may be hidden, the rules return "Check by hand", never "Seal". The eval marks every box that had a hidden item while it was packed and reports those failures separately from recognition failures. If occlusion causes most false SEALs, the next version captures per layer.
- **Decoys stay in production.** Every box, in the eval and in the live app, goes through the same code: the model sees the ordered SKUs, every look-alike, and 2 other SKUs from the seller's own catalogue, shuffled, with no quantities. It has to tell them apart, not confirm a list.
- **Three outcomes in the record, and in the interface.** SEAL, STOP_AND_FIX and UNCERTAIN are kept apart in the record, so a high false-STOP rate (the checks are wrong) can't be confused with a high UNCERTAIN rate (the photo is not good enough). The packer also sees them apart: "Stop and fix" means fix a known problem, and "Check by hand" means look closer. Neither lets the box be sealed.
- **Bounding boxes are for the evidence, not the decision.** The rules use only which SKUs were found, how many, and whether the whole box was visible. The boxes are drawn on the record so a person can see what each claim refers to. No rule reads box coordinates.

## Biggest risks

1. Look-alike variants (colour, size) that aren't visible in the photo. The mitigation is UNCERTAIN plus a hand check. Measured.
2. Stacked or hidden items (occlusion). Mitigations: UNCERTAIN, a second photo, and "spread them out". Measured as its own failure group.
3. No real customer has confirmed they'd pay. That's the first thing to test after the build.
