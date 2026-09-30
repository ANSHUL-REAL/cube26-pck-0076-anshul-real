# Pack evidence record (contract)

One record per outbound box, written when the box is checked before sealing.

Pack writes the organisers' **Evidence Contract 1.1** (the fixed interface Recovery reads) and keeps its own, richer record underneath. The contract record is made from ours by [`pack_manager/contract.py`](../pack_manager/contract.py). Nothing in the contract is renamed, dropped or repurposed, and everything of ours sits under `checks[].detail`, the one place the contract lets a Manager extend.

## Evidence Contract 1.1 (what Recovery reads)

| File | What it is |
|---|---|
| [`evidence-contract-1.1.schema.json`](evidence-contract-1.1.schema.json) | Section 2 written as a strict JSON Schema: no extra field anywhere except inside `checks[].detail` |
| [`examples-1.1/`](examples-1.1/) | The five examples below, in the contract's shape; a test checks they're valid and current |

**Endpoints** (section 3). Every one is scoped to the caller's organisation: send `X-Access-Code: <the org's code>`, or be signed in. No parameter names an organisation, and another organisation's record is a 404.

```
POST /v1/captures                   {"order_id": "ORD-1", "shots": 2}  -> {capture_id, upload_urls[], shots[]}
PUT  <each upload_url>              the photo's bytes (retrying replaces it)
POST /v1/captures/{id}/complete     -> {record_id, status, decision, record_url}
GET  /v1/records/{id}               -> the record
GET  /v1/records?since=&agent=&cursor=&limit=   -> {records[], next_cursor}
```

`GET /v1/records` returns records in the order they were saved; `since` filters on `captured_at`. Paging follows the save order, not `captured_at`: `captured_at` is taken when the photos arrive, before the model call, so a check that took longer is saved after a later one and would otherwise be skipped. `next_cursor` is null on the last page. To poll for new records, keep `resume_cursor` from the last response and pass it as `cursor`. A time without a zone is read as UTC. `agent` other than `pack` returns nothing, since this service only writes Pack records.

**Pack's check keys.** They're stable and lowercase, and every record has all seven in this order, whatever happened:

| `check_key` | pass | fail | uncertain |
|---|---|---|---|
| `image_quality` | local photo checks passed | — | a photo failed them and was used anyway (can never lead to SEAL) |
| `photo_reuse` | photo not used for another order | — | same photo already used for a different order, or not looked up (eval runs) |
| `scene_coverage` | whole box visible, nothing hidden | — | box cut off, or items may be stacked or hidden |
| `all_items_present` | every ordered product seen | an ordered product isn't in a fully visible box | can't tell |
| `quantities_correct` | every count equals the order | a count is short or over | a count can't be established |
| `no_extra_items` | nothing outside the order | a wrong product (look-alike) or an unknown product is in the box | could be an extra, a component or packaging |
| `order_matches_manifest` | the agent's decision was SEAL | STOP_AND_FIX | UNCERTAIN, or PENDING (the model didn't answer) |

Each check's `detail.source_checks` holds our checks it was built from (one per order line for `all_items_present` and `quantities_correct`). `order_matches_manifest.detail` holds the decision, reasons, fix steps, the model's object list with boxes on the photo, the agent and prompt versions, token usage, and our own record's id and hash. A rolled-up check fails if any part failed, is uncertain if any part couldn't be judged, and passes only if all passed. When the model didn't answer, every model-based check is `uncertain` with `detail.not_checked`.

`all_items_present`, `quantities_correct`, `no_extra_items` and `order_matches_manifest` are Pack's keys in the organisers' check-key registry (Recovery data contract, section 5). The other three are additions, which the registry allows. None will be renamed.

**Using Pack records against a charge** (Recovery data contract, sections 3, 6 and 7):

- **Join.** Match the charge's `amazon_order_id` to `subject.order_id`, or its `shipment_id` to `subject.shipment_id` when the order came with one. A Pack record covers a whole order (`subject.type` = `order`).
- **A charge on one product.** Use `all_items_present.detail.by_sku` and `quantities_correct.detail.by_sku` (and `by_asin`, when the catalogue has ASINs). They give that product's own verdict, so a charge on product A can be matched even if product B in the same box failed.
- **Mis-ship.** The evidence is `all_items_present` = pass and `quantities_correct` = pass, from a record captured before the charge event (`captured_at`).
- **Uncertain means no evidence.** Pack writes `uncertain` whenever the photo can't settle a point: hidden items, a failed photo check, or the model not answering. It is never a low-confidence pass, so treating it as no record, as section 6 says, loses nothing Pack actually saw.
- **Overrides.** The `checks` are always the agent's own results. A person's correction is in `overrides[]` with `from_verdict`, `to_verdict`, `reason`, `by` and `at`. An override applies to the whole check, including its `by_sku`: if `quantities_correct` has an override, its `by_sku` is the agent's view from before it. Whether a person's "pass" counts as evidence for a claim is Recovery's decision. Pack keeps both, so either choice can be made from the same record.
- **Not covered by Pack:** item condition. Pack checks what is in the box, not its condition, so it has no `condition_grade`.

**How our values fill the contract's fields:**

| Contract field | Pack writes |
|---|---|
| `record_id`, `organization_id`, `client_id` | UUIDs. New record ids are UUIDs. Our organisation ids are text (`org_demo_alpha`), so they map to a fixed UUIDv5, as do records saved before ids were UUIDs (`GET /v1/records/{id}` finds those too) |
| `agent` | `pack` |
| `subject.type` | `order`: Pack inspects an order (section 2 field notes) |
| `subject.sku`, `subject.asin` | the product when the order has one line, otherwise null (every line is in `quantities_correct.detail`) |
| `subject.shipment_id` | the order's outbound shipment, when the order came with one (`shipment_id` column in the orders CSV) |
| `subject.po_line_id` | null: an inbound concept |
| `subject.quantity_expected` | units ordered, all lines |
| `subject.quantity_observed` | product units the agent clearly counted in the box, ordered or not; null when it couldn't count (model didn't answer, an item was unclear, or units may be hidden) |
| `images[]` | `key` = the photo's random UUID, `sha256` of the stored photo, `bytes`, `taken_at` (= `captured_at`: EXIF times are stripped with the GPS). Size, role, the phone original's hash and the quality result are in `image_quality.detail.images` |
| `checks[].latency_ms` | the one model call's time for model-based checks; 0 for the local checks, which aren't timed |
| `outcome` | `decision` = SEAL / STOP_AND_FIX / UNCERTAIN / PENDING; `decided_by` = `agent`, or `operator` once a person decided |
| `overrides[]` | a person's correction of one check ("Override" on each check on the record page), or a person's decision on the box, as an override of `order_matches_manifest`. `reason` = the reason code, its meaning and the note. The reason is required: the form won't save without one. Correcting a check doesn't change the box decision |
| `status` | `pending` when the model didn't answer and no one has decided yet; otherwise `complete`. We never write `failed`: a capture whose photos can't be read is refused before any record exists |
| `content_hash` | as section 2 defines it: SHA-256 (hex) over the image hashes concatenated in order, then the `checks` array serialised as JSON with sorted keys and no whitespace. Checks never change after a record is written, so an override doesn't change it |

**A record link that needs no sign-in** (section 4). "Copy share link" on a record gives `/r/<signed token>`: a read-only page with that record's photos, the contract JSON and our record file. The token is signed with the app's secret, names one organisation and one record, and reaches nothing else. Anyone who has the link can view that record, so share it like the record itself.

**The capture page against section 4.**

Met:
- "Take guided photos" opens the rear camera (`getUserMedia`, HTTPS only), with a frame on screen and what each of up to three shots should show.
- Photos are sent with progress and retried when the connection drops.
- A failed model call still saves the photos and a `pending` record.
- Every check has an Override on the record page: pick a reason, then the result you found. A reason is required, and the agent's result stays on the record.
- The record link needs no sign-in.
- Once the photos are sent, a "Keep packing" link shows within 2 seconds.

**Where Pack doesn't meet section 4 yet**, to raise with the organisers rather than work around:

- *Presigned direct upload.* Photos go into the Postgres table under row-level security (section 5), not an object store, so the upload URLs point at the app itself. Each is a single-slot, 15-minute URL whose token is the permission, and retrying is safe, but the bytes do pass through the app server. Moving to an object store with presigned URLs is a storage change, not an API change.

## Our extended record

| File | What it is |
|---|---|
| [`pack-evidence-record.schema.json`](pack-evidence-record.schema.json) | JSON Schema, generated from the code (`EvidenceRecord` in `pack_manager/models.py`); a test fails if they drift |
| [`examples/seal.json`](examples/seal.json) | Correct box, with a promotional insert card that is ignored (a real record from the held-out run) |
| [`examples/stop_and_fix.json`](examples/stop_and_fix.json) | Missing and short products (a real record from the held-out run) |
| [`examples/uncertain.json`](examples/uncertain.json) | Products under a bin's netting, so presence and counts can't be settled (real record) |
| [`examples/overridden.json`](examples/overridden.json) | The same box after a person checked under the netting and stopped it (the decision the box's ground truth calls for; eval runs have no real hand decisions) |
| [`examples/pending.json`](examples/pending.json) | The vision model timed out; photos and record are still saved (scripted: the held-out run had no model failures) |
| [`build_contract.py`](build_contract.py) | Regenerates all of the above |

The examples come from the real pipeline (quality gate → decision rules → hash → override) with a scripted perception step and a synthetic photo, so they show the shape, not real model output. After the held-out eval, `python contract/build_contract.py --from-run test-v1` replaces the seal, stop, uncertain and pending examples with real records from that run.

## Fields

| Field | Meaning |
|---|---|
| `record_id` | A random UUID, so it isn't guessable (records before 30 Sep: `PCK-` + 12 hex characters) |
| `schema_version` | `cube.evidence.v1` |
| `organization_id` | Tenant: the seller or 3PL operating the pack bench (`org_demo_alpha`) |
| `client_id` | For a 3PL: the seller whose order this is. Null for a seller packing its own orders |
| `agent` | `name`, `version`, `prompt_version`, `model_version` (the exact vision model id) |
| `subject` | `type: "outbound_box"`, `order_id`, `unit_id`, `channel`, `shipment_id` (newer records), `expected_lines[] {sku, qty}` |
| `captured_at` | UTC time the photos were taken (server time) |
| `operator_label` | Who packed / checked the box |
| `images[]` | `image_id` (UUIDv4), `role`, `sha256` of the stored image, `original_sha256` of the upload, size, and the local `quality` gate result |
| `observations` | What was found: `uncertainty` (below), `expected_vs_observed[]`, `detected_items[]` (with `box_2d` on the photo), `missing[]`, `wrong[]`, `extra[]`, `over_quantity[]`, `unclear[]`, `non_product_items[]`, `scene`, token `usage`, `cost_usd`. On a retried check: `retry_of` (the record whose agent check didn't run), `retried_by`, `photos_taken_at`, and `disagreement` when the agent's new decision differs from a hand decision on the old record |
| `checks[]` | `check_key`, `verdict` (PASS / FAIL / UNCERTAIN / NOT_CHECKED), `confidence`, `detail`, `model_version`, `latency_ms`, `evidence`. All model-based checks share one `model_version` and `latency_ms` because they come from **one** model call |
| `outcome` | `decision` (SEAL / STOP_AND_FIX / UNCERTAIN / PENDING), `decided_by` (`agent` or `operator:<label>`), `decided_at`, `reasons[]`, `fix_instructions[]` |
| `overrides[]` | Each human decision: `original_decision`, `new_decision`, `reason_code`, `note`, `operator_label`, `at`, `prior_content_hash`, plus `prior_outcome` and `prior_status` (what it replaced). Appended, never replaced. With those, every earlier version of the record can be rebuilt and checked against its `prior_content_hash` (`pack_manager.evidence.verify_history`) |
| `status` | `final` (agent decided) · `pending_review` (agent said UNCERTAIN) · `pending` (model failed) · `overridden` (a human decided) |
| `content_hash` | `sha256:` over the canonical JSON of the record (sorted keys, no spaces, this field left out). It covers the image hashes |

### Our check keys (rolled up into the contract's keys above)

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

It shows whether a record's contents still match the hash: anyone can recompute it (`GET /api/records/{id}` returns `_hash_verified`). Offline, with the downloaded file (`?download=1`): `python -m pack_manager check-record <record>.json --photo <photo>` checks the hash, every earlier version, and whether a photo is one of the record's. Each override stores the hash from before it. Whoever can change a record can recompute its hash too, so it is **not** tamper-evident, immutable or anchored, and not an append-only log or a hash chain. The database refuses any change to a saved record except adding a hand decision at the end, even from the app's own role. The database owner could still turn that off and rewrite a record and its hash together.

## Reading our extended records

The contract endpoints above are what other pods should use. The older API returns our extended record:

```
GET /api/records?order_id=ORD-DUMMY-50044
GET /api/records?unit_id=UNIT-0044
GET /api/records/<record_id>
Header: X-Access-Code: <the org's access code>
```

Results are limited to the caller's organisation by Postgres row-level security. Another organisation's record returns 404, not 403. Photos are served only through `GET /images/{image_id}` to a signed-in user of the same organisation, or through a record's share link, which serves only that record's photos.

**Join keys.** In Pack, `unit_id` identifies a **whole box / order**, which can hold several SKUs and quantities (see FINDINGS.md). Join on `order_id` and match `sku` inside `expected_lines` / `observations.expected_vs_observed`.

## Name mapping to the other drafts

| Concept | Our extended record | Sample CSVs | Recovery contract-v0 draft |
|---|---|---|---|
| tenant | `organization_id` (+ `client_id`) | `org_id` | `org_id` |
| person | `operator_label` | `operator_id` | `operator_id` |
| check id | `check_key` | — | `check_id` |
| check result | `verdict` | — | `result` |
| hash | `content_hash` | — | `content_sha256` |
| decision | `outcome.decision` = `SEAL` / `STOP_AND_FIX` / `UNCERTAIN` / `PENDING` | `operator_verdict` = `seal` / `stop_and_fix` | — |
| all items present | one `line_present:<SKU>` check per order line (rolled up as `all_items_present` in 1.1) | — | `all_items_present` |
| quantities correct | one `line_quantity:<SKU>` check per order line (rolled up as `quantities_correct` in 1.1) | — | `quantities_correct` |
