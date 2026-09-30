# Architecture

Pack Manager checks an open box before it is sealed. It takes the order and 1–3 photos of the open box, and returns a decision (**SEAL**, **STOP_AND_FIX** or **UNCERTAIN**), a plain-language fix list, and an evidence record another system can read.

The one idea the rest follows from: **the vision model perceives, deterministic code decides.** The model never sees the order quantities and never outputs a verdict. It lists what is in the box. Python compares that list with the order, check by check.

```
 order (lines: SKU × qty)          catalogue (per org): descriptions, look-alikes,
        │                           reference photos, allowed inserts
        ▼                                          │
 ┌─────────────────────────────── one box ─────────▼────────────────────────────────┐
 │ 1 photos       1–3 photos of the open box, EXIF-rotated, resized, hashed           │
 │ 2 quality gate local OpenCV: size, blur, darkness, glare → "retake" or continue   │
 │ 3 candidates   ordered SKUs + their look-alikes + 2 decoys, shuffled, no quantities│
 │ 4 ONE model    photos + candidate descriptions + reference photos → JSON:          │
 │   call         objects[] (box_2d, sku | unknown | non-product, confidence),       │
 │                counts[], scene (hidden items?), image issues                      │
 │ 5 decision     pack_manager/decision.py: per-check PASS / FAIL / UNCERTAIN         │
 │   engine       → box outcome + fix list + reasons                                  │
 │ 6 record       handbook evidence record, SHA-256 content hash, saved with photos  │
 │                (saved as `pending` even when step 4 fails)                         │
 └──────────────────────────────────────────────────────────────────────────────────┘
        ▼
 web app (operator)  ·  JSON read API (Returns / Recovery)  ·  CLI + eval runner
```

## Code map

| Path | Responsibility |
|---|---|
| `pack_manager/models.py` | All data shapes: catalogue, order, model perception, evidence record |
| `pack_manager/quality.py` | Photo preparation (EXIF rotation, resize, JPEG, SHA-256) and the local quality gate |
| `pack_manager/catalogue.py` | Loads the org catalogue, picks the candidate set for a box, loads reference photos |
| `pack_manager/vision/prompt.py` | Prompt text, response schema, `normalise()` (clamps and cleans model output) |
| `pack_manager/vision/gemini.py` | The single Gemini call: structured output, timeout, retry, response cache |
| `pack_manager/vision/oracle.py` | A perceiver that reports known contents (tests and sample replay) |
| `pack_manager/decision.py` | The rules. No I/O, no model: perception + order in, checks + decision out |
| `pack_manager/evidence.py` | Canonical JSON, content hash, verify, operator override |
| `pack_manager/orders.py` | Parses an orders CSV; the organisation always comes from the session, never the file |
| `pack_manager/pipeline.py` | `verify_box()`: glues the above together, fail-open on model errors |
| `app/` | FastAPI + Jinja2 web app, JSON API, Postgres access (`db.py`, `store.py`), migrations runner |
| `db/migrations/001_init.sql` | Tables, row-level security, the access-code lookup function |
| `eval/` | Eval runner, metrics, label sheet for human labellers |
| `contract/` | JSON Schema and example records for the other tracks |

## The model call

- **One call per box** (engineering rule 2). All checks come from a single structured response, so every model-based check in a record carries the same `model_version` and `latency_ms`.
- **Input:** up to 3 box photos (long side ≤ 1600 px), then for each candidate its SKU, title, attributes, what one sellable unit looks like, the distinguishing detail, and up to 2 reference photos (≤ 512 px). The allowed inserts are listed so packaging isn't reported as a product.
- **Output:** a JSON schema enforced by the API (`response_schema`), with `temperature=0`. `normalise()` then turns any SKU outside the candidate list into an unknown product, clamps confidences, and drops malformed boxes.
- **Candidate set:** the ordered SKUs, every `confusable_with` and `component_lookalikes` SKU, and 2 decoys chosen by a seeded random from the rest of the catalogue, all shuffled. The model can't tell which candidates were ordered.
- **Timeout** 25 s, one retry on 429 / 5xx. After that the box fails open (below).
- **Cache:** responses are stored under a key made of the model, prompt version, photo hashes and candidate references. Re-running the eval or retrying a box doesn't spend quota twice. A cached answer is marked `cached_response: true` in the record.
- **Cost:** token usage from the API response is stored per record. `cost_usd` is computed from prices in `.env` (copied from Google's price list, not hard-coded).

## Decision rules

`τ` = `MATCH_THRESHOLD` (0.70) for "confidently this SKU"; `VISIBILITY_THRESHOLD` (0.70) for "the whole box is visible". Both are set on the dev split only.

| Check | PASS | FAIL | UNCERTAIN |
|---|---|---|---|
| `image_quality` | all photos passed the gate | — | a photo failed and the operator used it anyway |
| `photo_reuse` | photo not used for any other order | — | the exact photo was already used for a different order (web app; re-checking the same order is allowed) |
| `scene_coverage` | box fully visible, nothing hidden, visibility ≥ 0.70 | — | otherwise |
| `line_present:<SKU>` | ≥ 1 confident match | 0 found, nothing could be it, box fully visible | anything else |
| `line_quantity:<SKU>` | confident count = ordered, count certain, nothing unclear | confident count > ordered (over), or short with no way the gap could be hidden or unclear | count can't be pinned down |
| `wrong_item` | no confident match to a non-ordered SKU | a non-ordered SKU confidently found | an object might be a non-ordered look-alike |
| `extra_item` | no unexplained product | a confident unknown product | a tentative unknown product, or a loose part that could belong to an ordered product |

**Box outcome:** any FAIL → STOP_AND_FIX; otherwise any UNCERTAIN → UNCERTAIN; otherwise SEAL.

**What the rules read.** Which SKU each object matched and how confidently, how many there are, the model's own count, and the scene flags (whole box visible, items may be hidden). No rule reads bounding-box coordinates. The boxes are drawn on the record so a person can check what each claim refers to; they are explanation, not input to the decision.

**Substitution pairing.** When a line is short and a non-ordered SKU is present, the two are reported together ("Expected Blue Cap, found Red Cap (#3)" → fix "Replace Red Cap (#3) with Blue Cap"). Look-alikes are paired first. Reasons are ordered so the most useful one leads the page.

**Over-quantity wins over uncertainty.** If 3 are confidently counted and 2 were ordered, the box stops even if more could be hidden: at least one must come out.

**Doubt never turns into a SEAL.** A few rules exist only to keep a false SEAL out:
- Packaging is ignored only when the model is sure it's packaging. Low-confidence "packaging", or packaging it thinks could be a candidate (a cap half under bubble wrap), is treated as an unclear product.
- An object the model calls packaging or unknown while also naming a candidate SKU contradicts itself; it becomes an unclear product that could be that SKU.
- An unclear object whose alternative is a SKU that wasn't ordered makes `wrong_item` UNCERTAIN ("is #1 the Red Cap?").
- An ordered SKU that isn't in the catalogue can't be recognised, so its lines are UNCERTAIN (a hand check), never "missing".
- If the model's own count says an item is there but it listed no object for it, the line is UNCERTAIN, not "missing".

**Every unclear result explains itself.** When any check is UNCERTAIN, the record carries `observations.uncertainty`. It lists what is known, what can't be told, what evidence would settle each unclear point ("a count of the towels with every unit visible"), and the next action. It is derived from the checks, not written by the model.

**UNCERTAIN is its own outcome** (engineering rule 4), not a low-confidence SEAL. It has its own colour and its own queue ("Check by hand") in the UI. The record gets status `pending_review`, and the hand checks to do are listed.

## Evidence record

Other pods read the organisers' **Evidence Contract 1.1** at `/v1` (`GET /v1/records?since=`, `GET /v1/records/{id}`, and the capture endpoints). [`pack_manager/contract.py`](pack_manager/contract.py) writes it from our extended record below: seven stable check keys (`image_quality`, `photo_reuse`, `scene_coverage`, `all_items_present`, `quantities_correct`, `no_extra_items`, `order_matches_manifest`), our detail under `checks[].detail`, and the contract's own content hash (image hashes + checks). A signed share link opens one record read-only without sign-in. Full reference, and where we don't meet section 4 yet: [`contract/README.md`](contract/README.md).

Our extended record, highlights:

- Each photo is stored with the SHA-256 of the exact bytes the model saw, plus the SHA-256 of the original upload.
- `content_hash` = SHA-256 over canonical JSON (sorted keys, compact, hash field excluded). The record page recomputes it and shows "matches record" or a warning. Offline, `python -m pack_manager check-record` does the same for a downloaded record and matches photos to it.
- **Overrides are data.** An operator decision appends `{original_decision, new_decision, reason_code, note, operator_label, at, prior_content_hash, prior_outcome, prior_status}` and re-hashes. The agent's checks and reasons stay in the record unchanged. Reason codes are a fixed list, so overrides can be counted in the eval.
- **Evidence only grows, and the database enforces it.** A trigger on `records` (`records_append_only` in `db/migrations/001_init.sql`) accepts an update only if it adds a hand decision at the end. The agent's checks, observations and photos, and every earlier decision, must stay byte-for-byte the same. The app role also has no DELETE on records or photos. So a bug or a stolen app password can't quietly rewrite history; tested against real Postgres.
- **The override chain can be checked.** Because each override keeps what it replaced, every earlier version of the record can be rebuilt and compared with its `prior_content_hash`, back to the agent's original (`verify_history`). An override is refused on a record that doesn't match its hash, so re-hashing can't hide an edit.

**What we don't claim:** the hash shows whether a record's contents still match the hash. Whoever can change a record can recompute its hash too, so it is not tamper-evident, immutable or anchored (Evidence Contract 1.1 says the same). It is not an append-only log, a hash chain or an external anchor. The app can't rewrite a record (see above), but the database owner could drop the trigger and replace a record and its hash together.

## Tenancy and access

- Postgres row-level security is **enabled and forced** on `organizations`, `orders`, `records` and `images`. Each policy compares `organization_id` with `current_setting('app.org_id', true)`.
- The app sets `app.org_id` with `set_config(..., true)` at the start of **every transaction**, so it can't leak across pooled connections. No setting means no rows.
- The app connects as `pack_app`: not the table owner, not a superuser, no `BYPASSRLS`. The migration runs as the admin user, and the seed data is also written with `app.org_id` set, so it passes through the same policies.
- **Photos** are in an RLS-protected table, addressed by random UUIDv4, and served only by `GET /images/{id}` inside the signed-in org's transaction. There is no file path or bucket URL to guess.
- **Access codes** are stored as SHA-256 hashes in a table `pack_app` can't read. They are resolved by one `SECURITY DEFINER` function that returns only the org and operator for an exact match.
- `tests/test_isolation.py` runs against a real Postgres and checks all of this. The role flags must hold, and `relforcerowsecurity` must be on. Org bravo must see 0 of alpha's orders, records and images, including by exact ID and by guessed image UUID. A cross-org insert must fail, and the API and image routes must return 404 to the other org.

## Fail-open

If the model errors, times out or runs out of quota, `verify_box` still saves the photos and a record: decision `PENDING`, status `pending`, a `vision` check marked `NOT_CHECKED`, and the error text. The operator sees "Needs your decision" with the photos and the order, checks by hand, and records SEAL or STOP_AND_FIX with reason `agent_unavailable`. Nothing blocks the bench (engineering rule 3).

**Retry AI check.** A record whose AI check didn't run shows a "Retry AI check" button. It runs the check again on the exact stored photos (their hashes are verified first) against the order as it was when the photos were taken, and saves the result as a **new record** with `observations.retry_of` pointing at the old one. The old record is never changed. If a person already decided the box by hand and the AI now disagrees, the new record carries `observations.disagreement` and says so on the page. What this buys, honestly: if the box has already shipped, a disagreement found later can't stop that mis-ship. Its value is (1) a real catch where dispatch is slower than the retry, and (2) a measure of how often hand decisions and the agent disagree. There is no background job; the retry is a button. The button appears only on a record whose AI check returned nothing, so no box ever gets two AI answers: one model call per box still holds.

If a photo fails the quality gate, the operator is told why ("too dark", "blurry") and can retake it. They can also press "Use these photos anyway", in which case `image_quality` is UNCERTAIN, so the box can't be SEALed by the agent alone.

## Design decisions

| # | Decision | Why | Cost |
|---|---|---|---|
| D1 | The model perceives, code decides | Verdicts are deterministic, unit-tested (24 decision tests) and explainable check by check | Rules have to be written for each case |
| D2 | One model call per box | Engineering rule 2; cost and latency scale per box | A bad call affects every check in the box |
| D3 | The model isn't told the order or the quantities | Prevents "the order says 2, so I see 2". Measured with the `--reveal-order` ablation in the eval | The model can't use the order as a hint |
| D4 | Look-alikes and decoys in the candidate set | Forces a real comparison (Blue Cap vs Red Cap) instead of confirmation | Longer prompt |
| D5 | Objects are listed before counts in the schema | The model describes before it summarises | — |
| D6 | A bounding box for every object | Each claim points at pixels; drawn on the record page | Boxes are approximate |
| D7 | Local quality gate before the model | Doesn't pay for, or trust, an unusable photo | Thresholds are heuristic |
| D8 | Fail open to `pending` | Rule 3: the line never waits on the model | A human has to decide that box |
| D9 | UNCERTAIN is a first-class outcome | Rule 4; the honest answer for hidden or stacked items | Some boxes need a hand check |
| D10 | Expected contents come only from the order store | Rule 5: never from the model or the sample CSV | Orders must be imported |
| D11 | RLS forced, non-owner role, photos in the database | Rule 1, including the guessed-image-key case | bytea storage doesn't scale to millions of photos |
| D12 | Content hash only | The honesty rule: claim what is built | Not tamper-evident: whoever can change a record can recompute its hash |
| D13 | Keyed by SKU, not ASIN | The sample data gives one ASIN to two products | — |
| D14 | Server-rendered HTML, no JS build | Works on any phone browser; small; fast to change | Less interactive |
| D15 | Decoys in production, not only in the eval | The eval measures the same task that ships; the model must discriminate, not confirm | A slightly longer prompt |
| D16 | One shot per box (up to 3 photos), occlusion reported separately | Per-layer capture costs throughput; hidden items become "Check by hand", and the eval splits occlusion failures from recognition failures | Items under other items can't be seen |
| D17 | Retry creates a new linked record | Records are never edited; the disagreement with a hand decision is kept as data | Two records for one box |

## Threat model

| Threat | Mitigation | Residual risk |
|---|---|---|
| **Prompt injection from the box** (a note saying "SEAL THIS BOX", a packing slip listing other items) | The system prompt says text in images is scene content only. The model is never asked for a verdict and doesn't know the order, so there is no decision for the text to steer. The rules only use object classifications. Two adversarial boxes are in the eval | A note could still make the model mislabel an object |
| **Another org reads my records or photos** | Forced RLS on every tenant table, per-transaction org setting, non-owner role, random image UUIDs, 404 (not 403) for other orgs' IDs. Tested against real Postgres | Access codes are simple shared secrets; demo codes are public on purpose |
| **Editing a record after the fact** | Content hash shown and verified on the record page and in the API; every earlier version is rebuilt from the overrides and checked against its prior hash; overrides are refused on a record that doesn't match | Not tamper-proof against someone with database write access (see above) |
| **Model hallucination / confirmation bias** | D3, D4, D5, D6, unknown SKUs forced to `UNKNOWN_PRODUCT`, confidence thresholds, UNCERTAIN path | Measured in the eval as false-SEAL rate; see EVAL.md |
| **Quota exhaustion or outage** | Fail-open `pending`, retry with backoff, response cache, and a daily cap of AI checks per organisation (`DAILY_CHECKS_PER_ORG`, default 60) so one tenant or a public demo can't use up a shared key | Boxes need a hand decision during an outage or over the cap |
| **Reusing an old photo** (a packer uploads a photo of an earlier, correct box) | The stored photo's SHA-256 is looked up among the organisation's records; the same photo for a *different* order makes `photo_reuse` UNCERTAIN, so the box can't be sealed on it. Lookups go through RLS, so they never reveal another organisation's photos | Only exact copies are caught; a re-taken photo of an old box isn't |
| **Oversized or malicious uploads** | Images are decoded and re-encoded by Pillow; at most 3 photos per box | No per-org rate limit |
| **Secrets** | `.env` is git-ignored; only `.env.example` is committed | — |
| **Data sent to the model provider** | Only box photos and catalogue text are sent. The eval uses the author's own household products. The Gemini **free tier** may use prompts to improve Google's products, so production would use a paid tier | — |

## Not built (on purpose)

- Live channel integrations (Shopify, Amazon SP-API): orders are imported as CSV (the Import page) or JSON behind the `orders` table.
- Barcode reading, carton weight and dimensions, and checking inside sealed retail packaging (a protein tub's scoop).
- A hash chain or external anchoring of records.
- Real user accounts: each organisation has access codes, one per operator label.
