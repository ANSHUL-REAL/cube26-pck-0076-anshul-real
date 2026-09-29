# Pack evidence record (contract)

One record per outbound box, written when the box is checked before sealing. Field names follow the **handbook's evidence contract (section 9)**. The organisers have said there is no exact schema yet for `subject`, `agent`, `images` or `outcome`, so this file documents exactly what Pack writes.

| File | What it is |
|---|---|
| [`pack-evidence-record.schema.json`](pack-evidence-record.schema.json) | JSON Schema, generated from the code (`EvidenceRecord` in `pack_manager/models.py`); a test fails if they drift |
| [`examples/seal.json`](examples/seal.json) | Correct box (with a packing slip, which is ignored) |
| [`examples/stop_and_fix.json`](examples/stop_and_fix.json) | Wrong item: candle trio ordered, water bottle packed (sample row PCK-0044, which the human sealed) |
| [`examples/uncertain.json`](examples/uncertain.json) | 2 towels ordered, the second one is hidden under the first |
| [`examples/overridden.json`](examples/overridden.json) | The same box after the operator checked it by hand and chose SEAL |
| [`examples/pending.json`](examples/pending.json) | The vision model timed out; photos and record are still saved |
| [`build_contract.py`](build_contract.py) | Regenerates all of the above |

The examples come from the real pipeline (quality gate → decision rules → hash → override) with a scripted perception step and a synthetic photo, so they show the shape, not real model output. After the held-out eval, `python contract/build_contract.py --from-run test-v1` replaces the seal, stop, uncertain and pending examples with real records from that run.

## Fields

| Field | Meaning |
|---|---|
| `record_id` | `PCK-` + 12 hex characters. Random, so it isn't guessable |
| `schema_version` | `cube.evidence.v1` |
| `organization_id` | Tenant: the seller or 3PL operating the pack bench (`org_demo_alpha`) |
| `client_id` | For a 3PL: the seller whose order this is. Null for a seller packing its own orders |
| `agent` | `name`, `version`, `prompt_version`, `model_version` (the exact vision model id) |
| `subject` | `type: "outbound_box"`, `order_id`, `unit_id`, `channel`, `expected_lines[] {sku, qty}` |
| `captured_at` | UTC time the photos were taken (server time) |
| `operator_label` | Who packed / checked the box |
| `images[]` | `image_id` (UUIDv4), `role`, `sha256` of the stored image, `original_sha256` of the upload, size, and the local `quality` gate result |
| `observations` | What was found: `uncertainty` (below), `expected_vs_observed[]`, `detected_items[]` (with `box_2d` on the photo), `missing[]`, `wrong[]`, `extra[]`, `over_quantity[]`, `unclear[]`, `non_product_items[]`, `scene`, token `usage`, `cost_usd`. On a retried check: `retry_of` (the record whose AI check didn't run), `retried_by`, `photos_taken_at`, and `disagreement` when the AI's new decision differs from a hand decision on the old record |
| `checks[]` | `check_key`, `verdict` (PASS / FAIL / UNCERTAIN / NOT_CHECKED), `confidence`, `detail`, `model_version`, `latency_ms`, `evidence`. All model-based checks share one `model_version` and `latency_ms` because they come from **one** model call |
| `outcome` | `decision` (SEAL / STOP_AND_FIX / UNCERTAIN / PENDING), `decided_by` (`agent` or `operator:<label>`), `decided_at`, `reasons[]`, `fix_instructions[]` |
| `overrides[]` | Each human decision: `original_decision`, `new_decision`, `reason_code`, `note`, `operator_label`, `at`, `prior_content_hash`, plus `prior_outcome` and `prior_status` (what it replaced). Appended, never replaced. With those, every earlier version of the record can be rebuilt and checked against its `prior_content_hash` (`pack_manager.evidence.verify_history`) |
| `status` | `final` (agent decided) · `pending_review` (agent said UNCERTAIN) · `pending` (model failed) · `overridden` (a human decided) |
| `content_hash` | `sha256:` over the canonical JSON of the record (sorted keys, no spaces, this field left out). It covers the image hashes |

### Check keys

| `check_key` | PASS | FAIL | UNCERTAIN |
|---|---|---|---|
| `image_quality` | local photo checks passed | — | photo failed the checks and the operator used it anyway |
| `scene_coverage` | whole box visible, nothing hidden | — | box cut off, or items may be stacked or hidden |
| `line_present:<SKU>` | at least one found | none found in a fully visible box | can't tell |
| `line_quantity:<SKU>` | count equals the order | count is short or over | count can't be established |
| `wrong_item` | no product from outside the order | a different product or variant is in the box | an item might be a look-alike |
| `extra_item` | nothing unexplained | an unknown product is in the box | could be an extra, a component of an ordered item or packaging |
| `photo_reuse` | the photo hasn't been used for another order (web app only) | — | the exact photo was already used for a different order |
| `vision` | — | — | `NOT_CHECKED` when the model failed (fail-open) |

### `observations.uncertainty`

Present whenever a check is UNCERTAIN, otherwise `null`. It is built only from the checks, so it never says more than they do:

| Field | Meaning |
|---|---|
| `known` | Details of the checks that passed or failed |
| `unknown` | Details of the unclear checks, most important first |
| `missing_evidence` | What would settle each unclear check ("A count of Cotton Bath Towel with every unit visible.") |
| `next_action` | One sentence for the operator |

`qty` counts **sellable units**: an order of `SKU-MUG-11:2` (a set of 2 mugs) means 2 boxed sets, i.e. 4 mugs.

## What the content hash does and doesn't prove

It shows whether a record was changed after it was hashed: anyone can recompute it (`GET /api/records/{id}` returns `_hash_verified`). Each override stores the hash from before it. It is **not** an append-only log, a hash chain or an externally anchored proof. Someone with database access could rewrite a record and its hash together.

## Reading records (for Returns and Recovery)

```
GET /api/records?order_id=ORD-DUMMY-50044
GET /api/records?unit_id=UNIT-0044
GET /api/records/PCK-10F128797250
Header: X-Access-Code: <the org's access code>
```

Results are limited to the caller's organisation by Postgres row-level security. Another organisation's record returns 404, not 403. Photos are served only through `GET /images/{image_id}` to a signed-in user of the same organisation.

**Join keys.** In Pack, `unit_id` identifies a **whole box / order**, which can hold several SKUs and quantities (see FINDINGS.md). Join on `order_id` and match `sku` inside `expected_lines` / `observations.expected_vs_observed`.

## Name mapping to the other drafts

| Concept | This record (handbook) | Sample CSVs | Recovery contract-v0 draft |
|---|---|---|---|
| tenant | `organization_id` (+ `client_id`) | `org_id` | `org_id` |
| person | `operator_label` | `operator_id` | `operator_id` |
| check id | `check_key` | — | `check_id` |
| check result | `verdict` | — | `result` |
| hash | `content_hash` | — | `content_sha256` |
| decision | `outcome.decision` = `SEAL` / `STOP_AND_FIX` / `UNCERTAIN` / `PENDING` | `operator_verdict` = `seal` / `stop_and_fix` | — |
| all items present | one `line_present:<SKU>` check per order line | — | `all_items_present` |
| quantities correct | one `line_quantity:<SKU>` check per order line | — | `quantities_correct` |
