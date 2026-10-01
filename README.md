# Pack Manager

**Check an open box against its order before it is sealed, from a phone photo, and keep the proof.**

**Tested on real photos:** one frozen, held-out run on 50 real warehouse photos from the public Amazon Bin Image Dataset, misses included. A separate AI-generated set is reported on its own, never blended in.

**Check our numbers yourself (no API key, under a minute):**
- `python eval/metrics.py --run abid-test-v1` re-scores the saved held-out run and prints the table below (2/26, 12/24, 18/50). Use `--run abid-test-oracle` for the rules alone.
- Every box's photo hash, what the model saw, each check and the verdict are in [`eval/results/abid-test-v1/records/`](eval/results/abid-test-v1/records/). The settings and photo hashes were frozen in [`eval/frozen-test.json`](eval/frozen-test.json), committed before the run.
- `pytest` runs the 181 tests, including the rules and the company-isolation tests.

CUBE Buildathon · Round 2 · Track 03 (Pack Manager) · built by Anshul Nautiyal ([@ANSHUL-REAL](https://github.com/ANSHUL-REAL))

| | |
|---|---|
| Live demo | **https://pack-manager-lzht.onrender.com**: two one-click demo companies are on the sign-in page; more codes (per station, team lead, judge) in [ACCESS-CODES.md](ACCESS-CODES.md). Held-out results at [/results](https://pack-manager-lzht.onrender.com/results). Free plan: the first request after an idle spell takes about 30 s |
| Demo video | **[Walkthrough on a phone (73 s)](https://drive.google.com/file/d/1XUA13bPx-OnsVwq6Aykgf4V1BOyiOFsN/view?usp=sharing)**, recorded on the live site: sign in to the demo, pick an order, photograph the box, one real agent check (Stop and fix), the record, dark mode, Results. The wait for the agent is sped up 6× and says so on screen. Also a **[22 s launch video](https://drive.google.com/file/d/1n7FDk7PvG0FFWLT_tsoRyF9kLILPuy2l/view?usp=sharing)**. |
| Eval | [EVAL.md](EVAL.md): one frozen, held-out run of the real vision model on 50 real warehouse photos (public dataset). False SEAL 2/26, false STOP 12/24: a kill condition set in advance tripped, and we report it. Rules alone: 0 errors. A separate, disclosed set of 50 AI-generated boxes: false SEAL 1/26, false STOP 1/24. Also on the app's public `/results` page |
| How it works | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Record format for other tracks | [contract/](contract/README.md): the organisers' Evidence Contract 1.1, served at `/v1` |
| Problems found in the brief and data | [FINDINGS.md](FINDINGS.md) |
| Build log and hackathon documents | [submissions/anshul-real/](submissions/anshul-real/README.md) |
| Organisers' original brief | [docs/ORIGINAL-BRIEF.md](docs/ORIGINAL-BRIEF.md) |

---

## Problem understanding

A picker puts an order into a box and tapes it. If the wrong item, the wrong quantity or an extra item goes in, the result is a mis-ship: a refund, a return, a reshipment, customer-service time and often a bad review. Nobody checks, because checking every box by hand costs more than the mis-ships do.

**Who this is for:** sellers and 3PLs who pack their own orders (Amazon merchant-fulfilled, Shopify, Walmart, 3PL clients). Fully-FBA sellers don't need it, because Amazon packs those boxes. Three funded companies already sell pack verification into large distribution centres, with fixed camera stations. This is for the small seller or 3PL they don't sell to: **no station, no hardware, just a phone and a browser.**

**Two jobs, and the second matters more:**
1. **Catch the mistake** before the tape goes on.
2. **Prove what was sent.** A timestamped photo record of "contents at seal" answers the buyer's "item not received / empty box / wrong item" claim with more than the seller's word. The Returns and Recovery tracks read this record.

**The reframing that makes it feasible:** this isn't open-ended product recognition. We know what *should* be in the box, so it's **checking against a known order** (closed set), plus **spotting anything that doesn't belong** (open set). No per-product model training is needed: the model gets reference photos of the ordered products and their look-alikes, and compares.

## Solution overview

1. The day's orders are imported from a CSV (`order_id`, `order_lines` like `SKU-A:2;SKU-B:1`, optional `shipment_id`). The operator signs in, picks the order and takes 1–3 guided photos of the open box with the phone camera (a frame on screen says what each shot should show), or chooses photos.
2. A local photo check rejects blurry, dark or glare-heavy photos immediately ("Retake: photo looks blurry"), before any model call.
3. **One** vision-model call lists every object in the box, with a bounding box. The model is not told the order or the quantities.
4. Deterministic rules compare that list with the order, check by check, and decide:

| Outcome | Meaning | Shown as |
|---|---|---|
| **SEAL** | Every line present, right quantities, nothing wrong or extra | Green "Seal the box" |
| **STOP_AND_FIX** | Something is missing, wrong or extra | Red "Stop and fix", plus exact fixes: "Replace Red Cap (#3) with Blue Cap", "Add 1 × Blue Towel", "Remove USB-C Cable (#4)" |
| **UNCERTAIN** | The photos can't support a reliable answer (stacked items, a look-alike whose label isn't visible, part of the box cut off) | Amber "Check by hand", plus exactly what to check |
| PENDING | The model didn't answer (timeout, quota) | Grey "Needs your decision"; photos and record are kept. "Retry agent check" runs it again later as a new, linked record |

5. Every box gets an **evidence record**: the order, photos (with hashes), what was found, every check with its verdict and confidence, the decision and why, and a content hash. The operator can disagree; the override is appended with a reason code, and the agent's original answer is kept.
6. Returns and Recovery read records in the organisers' **Evidence Contract 1.1** shape at `/v1`, limited to their own organisation. Each check (`all_items_present`, `quantities_correct`, `no_extra_items`, `order_matches_manifest`, and more) carries a verdict per ordered product, and a person can override any check with a required reason. A record's share link opens it read-only for a customer, with no sign-in.

**Sample-data check.** Replaying the organisers' `pack_sample.csv` with its `observed_in_box` column as perfect perception: 4 of the 29 boxes have wrong contents. **The rules stop all 4. The human operator in the data sealed 2 of them.** No correct box is stopped. This tests the rules alone, not the vision.

```bash
python -m pack_manager replay-sample
```

### Sign-in: why access codes, not accounts

Packers sign in with a short access code, not an email and password or a Google account. That's a choice, made for how packing benches work:

- **Stations are shared.** Several packers use one phone or tablet over a shift. Typing a personal password between boxes is what warehouses avoid; they use badge scans and PINs. A code is the browser version of that.
- **The code decides the company and the name on the record.** Each code maps to one organisation and one operator label (a person or a station), and that label is stamped on every check and override. Nothing in the request can name a different organisation.
- **The database, not the app, keeps companies apart.** Every tenant table has row-level security, enabled and forced, for a role that isn't the owner. A wrong code or another company's record ID gives a 404, and that is tested against real Postgres.
- **Codes are never stored.** Only their SHA-256 is kept, in a table the app's role can't read, and one database function answers "which company and operator is this?" for an exact match.
- **No personal data.** No emails, passwords or names are collected, so there is nothing to leak or reset.
- **One login for people and programs.** Returns and Recovery send the same code in an `X-Access-Code` header to read `/v1`.

The demo codes are public on purpose, so judges can get in with one click: `alpha-demo` and `bravo-demo` on the sign-in page, plus per-station, team-lead and judge codes in [ACCESS-CODES.md](ACCESS-CODES.md). Each demo company is capped at 60 agent checks a day to protect the shared model key.

**What codes don't do:** they identify a station or role, not a verified person, and they don't expire. Next steps: a team-lead page to issue and revoke codes, then company single sign-on (Google Workspace or Microsoft, via OIDC) for team leads. Packers would keep codes, because sign-on doesn't suit a shared bench device.

## Results

One held-out run on **50 real warehouse bin photos** from the public Amazon Bin Image Dataset. We had no products or labellers for a home shoot; see [EVAL.md](EVAL.md) for why, and what that changes. Ground truth is Amazon's record of each bin; the orders were written before any run.

| | Result (95% CI) |
|---|---|
| **False SEAL** (a wrong box would ship) | **2/26, 8% (2–24%)** |
| False STOP (a good box stopped) | 12/24, 50% (31–69%) |
| Sent to a person (UNCERTAIN) | 18/50, 36% (24–50%) |
| Model failures | 0/50 |
| Same boxes, perfect perception (rules alone) | 0 errors |

**A kill condition tripped** (false STOP above 15%). On these photos, with `gemini-3.5-flash-lite`, the agent should record evidence and let a person decide, not gate sealing. The rules made no errors, so every error came from what the model saw. The main one: calling a strapped, cluttered bin "fully visible" and then missing a product.

**A second, separate set: 50 AI-generated boxes** (open shipping boxes on a bench, every image generated and disclosed as such). With the same frozen model and prompt: false SEAL 1/26, false STOP 1/24, UNCERTAIN 2/50. These images are cleaner than real photos, so this is not evidence about real photos, and it's never blended with the numbers above. Its one false SEAL is a boxed product the model called packaging. Details: [EVAL.md](EVAL.md#a-second-set-ai-generated-boxes-reported-separately-never-blended).

**Kill condition:** if the held-out false-SEAL rate is above 5% while UNCERTAIN is 25% or lower, the agent isn't fit to gate sealing. It should then run only as an evidence recorder (photo + record, no verdict).

## Usage

**On the live site** (https://pack-manager-lzht.onrender.com, nothing to install):
1. Tap **Try the demo** and pick a demo company (or sign in with a code from [ACCESS-CODES.md](ACCESS-CODES.md)).
2. **Orders** lists today's orders still to check. Open one to see what should be in the box.
3. Tap **Take guided photos** (or choose up to 3 photos of the open box), then **Check this box**.
4. Read the answer: **Seal the box**, **Stop and fix** (with exactly what to swap, add or remove), or **Check by hand** (with what to check). The photo shows numbered boxes on what the agent found.
5. Disagree? Use **Override** on any check, with a reason. The agent's original answer is kept.
6. **Records** lists every checked box, and each record has a read-only share link. **Results** shows the held-out eval.
7. Other systems read the same records as JSON: `curl -H "X-Access-Code: alpha-demo" https://pack-manager-lzht.onrender.com/v1/records`.

**From the command line:** `python -m pack_manager replay-sample` replays the organisers' sample CSV through the rules, and `python eval/metrics.py --run abid-test-v1` re-scores the held-out run.

## Setup: run it locally

Needs Python 3.12+ and Postgres 16 (Docker or any hosted Postgres).

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```
(on macOS/Linux: `source .venv/bin/activate`)

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in `GEMINI_API_KEY` (from Google AI Studio). Without a key the app still runs, and every box comes back PENDING (fail-open).

```bash
docker compose up -d db
```
(or put a hosted Postgres admin connection string, e.g. Neon's, in `DATABASE_ADMIN_URL` and leave `DATABASE_URL` empty: the migration fills it in with the restricted `pack_app` role on the same host)

```bash
python -m app.migrate
```
This creates the tables, row-level security policies, the restricted `pack_app` role, two demo organisations and the sample orders.

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000 and sign in with **`alpha-demo`** (Alpha Outfitters) or **`bravo-demo`** (Bravo Supplies). These demo codes are public on purpose.

**Command line (no database needed):**

```bash
python -m pack_manager verify --catalogue catalogue/sample --order order.json --photo box.jpg
```

```bash
python -m pack_manager check-record PCK-0123456789AB.json --photo box.jpg
```

That checks a downloaded evidence record on its own, e.g. to answer a buyer's "item missing" claim. It reports whether the record matches its content hash, whether every earlier version matches too, and whether each photo is one of the record's (the stored copy or the phone original). A record page also prints as a one-page evidence sheet (**Print evidence**).

```bash
python -m pack_manager models
```

**Tests:**

```bash
python -m pytest
```
The tenant-isolation tests run against real Postgres and are skipped when `DATABASE_URL` and `DATABASE_ADMIN_URL` aren't set. CI runs them against a Postgres service.

| Suite | Tests | What it covers |
|---|---|---|
| `test_decision.py` | 31 | The rules: the eight scenarios from the brief, look-alikes, multipacks, hidden items, prompt injection |
| `test_pipeline.py`, `test_core_hardening.py` | 19 | Photo gate, fail-open, one model call per box, hashing, the override chain, bad inputs |
| `test_isolation.py` | 9 | Real Postgres: row-level security, the app role's rights, append-only records, the `/v1` API and share links |
| `test_pages.py`, `test_web_hardening.py` | 57 | Every page and API route, CSRF, uploads, conflicts, CSV export |
| `test_contract.py`, `test_check_record.py` | 6 | The published schema matches the code; a downloaded record checks out on its own |
| `test_contract11.py` | 17 | Evidence Contract 1.1: exact shape (strict schema), its content hash, the four `/v1` endpoints, fail-open captures, the no-sign-in record link |
| `test_eval*.py`, `test_plan_boxes.py`, `test_sample_and_prompt.py` | 32 | Box plan, photo import, label sheet, freeze, metrics, the organisers' sample replay, what the model is shown |

Each hard rule in [CLAUDE.md](submissions/anshul-real/CLAUDE.md) has a test that fails if it's broken:

| Rule | Test |
|---|---|
| The model perceives, code decides | `test_decision.py::test_a_seal_this_box_note_cannot_seal_a_wrong_box` |
| The model never sees the order | `test_sample_and_prompt.py::test_candidates_include_lookalikes_and_hide_the_order` |
| One model call per box | `test_pipeline.py::test_one_model_call_per_box_carries_every_check` |
| Fail open | `test_pipeline.py::test_fail_open_keeps_photos_and_marks_pending` |
| A failed photo never seals | `test_decision.py::test_forced_bad_photo_never_seals` |
| Tenancy (RLS forced, restricted role) | `test_isolation.py::test_app_role_cannot_bypass_rls` and the rest of that file |
| Overrides are data, evidence only grows | `test_core_hardening.py::test_override_chain_can_be_rebuilt_and_checked`, `test_isolation.py::test_records_are_append_only` |
| Evidence follows the contract | `test_contract11.py::test_every_record_is_exactly_the_contract_shape`, `test_contract.py::test_published_schema_matches_the_code` |
| No GPS in committed photos | `test_eval_tools.py::test_saved_copies_have_no_gps_exif_or_comment` |
| Held out means held out | `test_eval_tools.py::test_split_all_needs_the_test_freeze` |

## Deploy

1. A hosted Postgres (e.g. Neon). Put its admin connection string in `DATABASE_ADMIN_URL` locally and run `python -m app.migrate --no-sample-orders` once. This creates the tables, policies and the restricted `pack_app` role, without the organisers' dummy orders: the live demo shows only real orders, imported on the Import page or from `catalogue/<org>/orders.json`.
2. On Render: **New → Blueprint** and pick this repository ([`render.yaml`](render.yaml)). Set `DATABASE_URL` to the **`pack_app`** connection string (never the admin one; the migration wrote it to your local `.env`) and `GEMINI_API_KEY`.
3. Check `https://<your-app>.onrender.com/healthz`. The free plan sleeps when idle, so the first request can take ~30 s.

## Repository

| Path | What |
|---|---|
| `pack_manager/` | The agent: photo quality gate, catalogue, the vision call, decision rules, evidence record |
| `app/` | Web app (FastAPI, server-rendered pages) and JSON API |
| `db/migrations/` | Postgres schema with forced row-level security |
| `catalogue/` | Product descriptions and reference photos per organisation, and a builder that turns a spreadsheet + photo folders into `catalogue.json` |
| `contract/` | Evidence Contract 1.1 schema and examples, and our extended record's schema and examples |
| `eval/` | Eval runner, metrics, label sheet, photo importer (strips GPS), manifest of real packed boxes |
| `tests/` | Decision scenarios, pipeline, contract, web pages, tenant isolation |
| `docs/` | Photo guide, organisers' original brief |
| `data/` | Organisers' synthetic sample (unchanged) |

## Assumptions

- **An order line's `qty` counts sellable units**, not physical objects. `SKU-MUG-11:2` (a set of 2 mugs) means 2 boxed sets. The catalogue says what one unit looks like.
- **The order is the authority** for what should be in the box (engineering rule 5). It is imported, never inferred by the model or taken from the sample CSV's observations.
- In Pack, **`unit_id` means a box/order**, because the sample has multi-SKU, multi-quantity rows under one `unit_id`. Records are also keyed by `order_id`.
- **UNCERTAIN is a third box outcome** (don't seal until a human confirms), although the brief names two decisions. It is asked of the organisers and listed as a finding.
- Packing slips, invoices, inserts and dunnage are never "extra items". The list is configurable per organisation.
- Products are keyed by SKU, not ASIN, because the sample data gives one ASIN to two products.

## Limitations

- **Can't see inside sealed retail packaging.** A missing scoop inside a sealed protein tub can't be detected, and a Pack record can't disprove that claim.
- **Stacked identical items** are often UNCERTAIN rather than counted. This is by design, and it costs a hand check.
- **Look-alike variants** (colour, size) are only as good as what the photo shows. When the deciding detail isn't visible, the answer is UNCERTAIN.
- **Evaluated on warehouse bin photos from a public dataset,** not on a packing bench and not on our own capture. No human labellers; ground truth is Amazon's record. Bench conditions (one open box, phone camera) are likely easier, but that's untested.
- **Gemini free tier:** rate limits apply, and Google may use free-tier prompts to improve its products, so only public dataset photos and AI-generated images were sent during the build. Production would use a paid tier.
- The content hash shows whether a record still matches what was hashed. Whoever can change a record can recompute its hash, so it is **not** tamper-evident, immutable, append-only or anchored.
- No live Shopify or Amazon connection, no barcode scanning, no carton weight. Access is by per-operator codes, not full user accounts  (see [Sign-in](#sign-in-why-access-codes-not-accounts)).
