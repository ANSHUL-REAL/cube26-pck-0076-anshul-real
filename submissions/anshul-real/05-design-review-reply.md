# Reply to the design review

Thanks for the review. Here's what you asked for, with the changes it led to. All targets below were written before any real box was photographed.

## 1. UNCERTAIN rate target

UNCERTAIN ("Check by hand") is a first-class metric: **target ≤ 25% of boxes, kill above 40%**. It's also part of the main kill condition: a false-SEAL rate above 5% while UNCERTAIN is 25% or lower means the agent must not gate sealing and runs only as an evidence recorder.

We keep the three outcomes apart in the record, as you suggested. We also keep them apart on screen: "Stop and fix" means fix a known problem, and "Check by hand" means look closer. Neither lets the box be sealed.

## 2. Fail-open and the pending rate

We adopted your framing: when the model fails, the packer seals on their own judgment, exactly as they would with no agent. Nothing waits on the agent.

- **PENDING rate target: ≤ 2% of boxes, kill above 5%.**
- **About the "async re-run" in my question:** it didn't exist when I asked. There is now a "Retry agent check" button on any box whose check didn't run. It re-checks the exact stored photos (hashes verified) against the order as it was, and saves a new record linked to the old one. If a person already decided and the agent disagrees, the new record says so.
- **What it buys:** it doesn't recall a box that has already shipped. Its value is a real catch where boxes wait before dispatch, plus a measure of how often hand decisions and the agent disagree. The PR/FAQ now says this. It's a button, not a background job.

## 3. Occlusion

**We picked single-shot, with occlusion reported separately.**
- The packer takes one photo of the open box, or up to 3 if items are stacked. Per-layer capture costs throughput, which is what packers are measured on.
- When the model reports that items may be hidden, the rules return "Check by hand", never "Seal".
- While packing each eval box, we mark in the manifest any box where an item is partly under another item or filler (`hidden`). The report gives those boxes their own group, so geometry failures aren't counted as recognition failures.
- If occlusion turns out to cause most false SEALs, per-layer capture is the next version.

## 4. Decoys in production

**Yes.** The eval and the live app use the same candidate code: the ordered SKUs, every look-alike, and 2 other SKUs from the seller's own catalogue, shuffled, with no quantities. The eval measures the task that ships.

## 5. Identity and count as separate rows

The per-check table has separate rows:
- `all_items_present`, scored from `line_present:<SKU>` per order line;
- `quantities_correct`, scored from `line_quantity:<SKU>` only on lines whose item is really in the box.

We expect counting to be the weaker row and will report the gap.

## 6. Bounding boxes

They are for the evidence record, not the decision. The rules read only which SKUs matched, how many, and whether the whole box was visible. The boxes are drawn on the record so a person can see what each claim points at. This is now stated in the build brief and ARCHITECTURE.md.

Where to look: [one-pager](03-one-pager.md) (targets and design choices), [EVAL.md](../../EVAL.md) (metrics), [ARCHITECTURE.md](../../ARCHITECTURE.md) (decisions D15–D17, fail-open).
