# Findings

The rules say contradictions are findings: raise them, don't silently pick a side. These were found by reading the handbook, all five track repositories (READMEs, rules, sample data, issues) and the Verity background documents, and by running scripts over the sample CSVs (28 Sep 2026). Each finding says what's wrong, why it matters, and what this build does about it.

🔴 changes what gets built · 🟠 changes evaluation or integration · 🟡 documentation

## Pack track

**P1 🟠 The sample data doesn't contain the cases its README promises.** `data/README.md` says rows differ by missing item, short quantity, extra item and wrong item, and that `uncertain` / `pending_review` appear on purpose. `pack_sample.csv` (29 rows) has 4 discrepant rows: 3 extra items (all `SKU-CABLE-USBC`) and 1 wrong item. There are no missing-only, short-quantity, uncertain or pending rows. *Handling:* the sample is used for schema design and a rule replay only. The eval set is built to cover all eight scenarios.

**P2 🟡 The operator verdict is wrong in half the discrepant boxes.** PCK-0034 (extra cable) and PCK-0044 (candle trio ordered, water bottle packed) are marked `seal`. The README says this is deliberate, so `operator_verdict` can't be ground truth. *Handling:* it is used as the human baseline. The rules stop 4 of 4; the operator stopped 2 of 4.

**P3 🔴 In Pack, `unit_id` identifies a whole box, not a unit.** 7 of 29 rows are multi-SKU and 7 have qty > 1. For example, UNIT-0057 is 2 protein tubs + 1 leash, three items under one `unit_id`. In Receiving it's a PO line; in the fee report it's a single unit. *Handling:* Pack records are per box, carry `order_id` and `expected_lines[] {sku, qty}`, and the contract says to join on `order_id` + `sku`.

**P4 🔴 Multipack SKUs: order quantity ≠ number of objects in the photo.** `SKU-MUG-11` is a set of 2 mugs and `SKU-CANDLE-3` is a trio, so `SKU-MUG-11:2` means 4 mugs in the box. Nothing says whether `qty` counts sellable units or objects. *Handling:* `qty` = sellable units, and each catalogue entry describes one unit. This is stated as an assumption.

**P5 🔴 A product's component collides with a separate SKU.** `SKU-LAMP-LED` ships with a USB cable, and `SKU-CABLE-USBC` is sold on its own. Every extra item in the sample is a USB-C cable. A loose cable next to a lamp could be an extra SKU or the lamp's own cable. *Handling:* the catalogue field `component_lookalikes`; such an object makes `extra_item` UNCERTAIN, not FAIL.

**P6 🔴 Two decisions, but UNCERTAIN is "a valid outcome".** The problem statement names the decision as SEAL or STOP & FIX, and also says UNCERTAIN is valid and not to force a conclusion. The handbook describes Pack as deciding whether an item can "proceed, needs correction, or should stop". *Handling:* the box outcome is SEAL / STOP_AND_FIX / UNCERTAIN, where UNCERTAIN means don't seal until a human confirms. The organisers were asked.

**P7 🟠 "Fail open" vs "verify before sealing".** Engineering rule 3 says a model error must never block the operator. Pack's whole purpose is to stop an unverified box from being sealed. *Handling:* on model failure the record is saved as `pending` and the operator decides by hand (reason `agent_unavailable`). The record shows that no agent check ran.

**P8 🔴 Catalogue and product images are listed as inputs but none are provided.** The only catalogue-like data is in the Receiving sample. The 10 sample SKUs are all visually distinct, yet "visually similar products" is a required test scenario. *Handling:* our own catalogue with reference photos and look-alike pairs.

**P9 🟠 Recovery can't use any Pack record in the sample.** None of the 29 Pack units appear in `fee_report_sample.csv`, and there is no charge type for merchant-fulfilled disputes (wrong item, item not received, A-to-z). Yet Recovery is described as consuming Pack records for exactly these claims. *Handling:* the record carries what such a claim needs: the photo at seal, `captured_at`, per-line contents and `content_hash`.

**P10 🟠 Returns can't be reconciled with multi-line or multi-quantity boxes.** Returns has a single `ordered_sku` and no quantity. UNIT-0009 shipped a puzzle and a bottle, and the return lists only the puzzle. RTN-0097 reports a missing scoop inside a protein tub that Pack sealed, which no Pack photo can show. *Handling:* documented as a scope limit; the contract proposes `sku` + `qty` per returned line.

## Across tracks

**X1 🔴 One ASIN on two products.** `B0DUMMY357` is both `SKU-LAMP-LED` and `SKU-PROT-1KG`, consistently across Receiving, Prep and Returns. Any ASIN-keyed lookup returns the wrong product. *Handling:* everything is keyed by SKU within an organisation; ASIN is an attribute.

**X2 🔴 Three naming conventions for the evidence record.** The handbook uses `organization_id`, `operator_label`, `check_key`, `verdict` and `content_hash`. The sample CSVs use `org_id` and `operator_id`. The Recovery draft uses `check_id`, `result` and `content_sha256`. *Handling:* handbook names are used, and a mapping table is in [contract/README.md](contract/README.md).

**X3 🟠 RULES.md differs between tracks.** In the Returns repository, the engineering rules are softer: RLS applies "if your implementation stores persistent data", batching applies "where checks can be safely evaluated together", and fail-open allows several statuses. *Handling:* the stricter version is followed.

**X4 🟡 Leftovers from an older workflow.** `submissions/_TEMPLATE` (customer letter, PR/FAQ, build log, contract folder) and the PR template assume PRs into the official repository. The handbook says fork, no PR, submit the URL. The Pack README mentions "two weeks"; Round 2 is about six days. *Handling:* fork only; no PR to the official repository.

**X5 🟡 The "domain brief" isn't anywhere.** Every README lists a domain brief on warehouse economics "shared by the organisers". It isn't in any repository.

**X6 🟠 "Packaging readiness" or contents?** The handbook says Pack assesses packaging readiness; the repository and problem statement say contents verification. *Handling:* contents are in scope; packaging condition isn't.

## Background documents (Verity) vs this track

- The Verity plan explicitly puts pack verification later ("three funded competitors already are"). This build's wedge is the small seller with no station or hardware.
- Verity's cost model assumes one decision per return; Pack runs on **every** order. Cost per box is measured and reported in the eval.
- Verity mentions an append-only record and a hash chain. This build has a content hash only and says so.
- The only customer voice is a synthetic prep-centre owner. There's no merchant-fulfilled seller voice, so this is untested demand.
