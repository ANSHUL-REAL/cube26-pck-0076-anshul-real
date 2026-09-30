# Build log

Newest first. Decisions, what changed, and what's still open. Dates are IST.

## Thu 1 Oct

- **Recovery data contract** read. Its check-key registry lists exactly Pack's four keys (`all_items_present`, `quantities_correct`, `no_extra_items`, `order_matches_manifest`), so nothing is renamed. Our three other keys are additions, which it allows. Charges can name one SKU or ASIN while a Pack record covers a whole order, so `all_items_present` and `quantities_correct` now carry each ordered product's own verdict (`detail.by_sku`, `by_asin`). `contract/README.md` explains how Recovery joins a charge to a Pack record, and why Pack's `uncertain` is safe to treat as no evidence.
- **An override on every check** (Evidence Contract 1.1, section 4). Each of the seven checks on a record page has its own Override, with a required reason and an optional note. The correction is appended to the record with the result it replaced. The AI's checks, the box decision and the contract's content hash stay as they were. Older records keep their hashes: a box decision is still written exactly as before. Tested against real Postgres too, where the append-only rule accepts it.

## Wed 30 Sep

- **Evidence Contract 1.1** (the organisers' fixed record for Recovery) arrived today. Our record used the handbook's names, but with different shapes: per-product check keys, an `agent` object, no `shipment_id`, and a hash over the whole record. Pack now writes the contract exactly, from our richer record. Nothing is renamed or dropped, and our extras go under `checks[].detail`. The changes:
  - **Seven stable check keys:** `image_quality`, `photo_reuse`, `scene_coverage`, `all_items_present`, `quantities_correct`, `no_extra_items`, `order_matches_manifest`.
  - **The contract's content hash:** image hashes plus checks. Overrides don't change it.
  - **All four `/v1` endpoints.** Captures return one upload URL per shot, can be retried, and fail open to `pending`.
  - **A read-only record link that needs no sign-in,** signed for one record and its photos.
  - **`shipment_id`** on orders.
  - **Wording:** the docs no longer come close to calling the hash tamper-evident.
  - **Open, to raise with the organisers:**
    - Photos pass through the app server, because they're stored under row-level security in Postgres, not in an object store with presigned URLs.
  - **Records unchanged:** the held-out numbers were measured with the decision code this doesn't touch.
- **Second eval set, AI-generated and disclosed.** 70 boxes, planned before any image was made. With the same frozen model and prompt, nothing tuned: false SEAL 1/26, false STOP 1/24, UNCERTAIN 2/50. It's reported apart from the real photos and never blended, because generated scenes are cleaner than real ones. Its one false SEAL (a boxed mug set called packaging) is the same kind of miss as the bin set's.

- **Held-out eval run, on a public dataset.** No products or labellers were available for a home shoot, so the eval uses 70 real warehouse photos from the Amazon Bin Image Dataset (CC BY-NC-SA 3.0 US). The orders were written from a fixed seed before any model run; ground truth is Amazon's record of each bin.
  - **Free-tier quota:** the Gemini key allows 20 `gemini-2.5-flash` calls a day, and 2.5-flash-lite is closed to new users. The app and the eval moved to `gemini-3.5-flash-lite`.
  - **Dev:** the lite model called strapped, cluttered bins "fully visible" and stopped good boxes. Prompt `pack-v3` asks for strict visibility answers, and false STOPs halved on dev.
  - **Held-out (50 boxes, frozen first):** false SEAL 2/26 (8%), false STOP 12/24 (50%), UNCERTAIN 18/50, no model failures. The false-STOP kill condition tripped, so on these photos the agent records evidence and a person decides. With perfect perception the rules made no errors; every error was the model's.
  - Contract examples are now real records from that run.

- **Box plan before the shoot.** `eval/plan_boxes.py` plans all 70 boxes from the catalogue and writes the manifest (the answer key) before any photo exists, plus a phone checklist to pack from. It checks its own plan: every box can be packed with what's at home (a new `on_hand` column in `products.csv`), and every kind of box has the truth it's meant to have. Kinds are shuffled, so a box number doesn't give its answer away.
- **Test set cut from 60 to 50 boxes** to match the brief's "50 units", before any photo was taken. 24 should seal and 26 should stop.
- The photo import takes the whole shoot (practice and test boxes) in one go.
- **Dry run of the whole eval** on dummy photos, in a throwaway copy of the repo: product sheet, catalogue, plan, 70-photo import, label sheet, two label files, freeze, held-out run, report. Every step worked. It found one bug (running the eval without an API key crashed instead of saying what to do). New `--oracle` run: perfect perception from the manifest, to measure the rules alone. On the planned mix the rules decided all 50 boxes as the manifest says.
- **Second look at the other forks** (nine with real builds; ideas only, no code copied). None has run a vision model on real box photos; several publish accuracy numbers with nothing behind them. Taken from that review:
  - **Records are append-only in the database.** A trigger refuses any update that doesn't just add a hand decision at the end, even from the app's own role. Tested against real Postgres.
  - The result page shows how long the AI check took.
  - Tests that pin two rules that had none of their own: one model call per box, and a "SEAL THIS BOX" note can't seal a wrong box. The README maps each hard rule to its test.
  - The demo script shows fail-open (a check that can't run leaves the photos and a "Needs your decision" record).
- **Evidence for buyer claims** (the Recovery step). A record page prints as an evidence sheet, and `python -m pack_manager check-record` checks a downloaded record away from the app: its hash, every earlier version, and whether a photo is one of its own (the stored copy or the phone original). Tried on a live record from the hosted database.

## Tue 29 Sep

- **Design review of the UNCERTAIN and fail-open questions.** Both calls were confirmed. The review asked for four things, now answered in [05-design-review-reply.md](05-design-review-reply.md):
  - a target for the UNCERTAIN rate (it was already in the one-pager: ≤ 25%, kill above 40%), now joined by a PENDING target of ≤ 2%;
  - an occlusion stance: one shot per box, with boxes that had a hidden item marked while packing and reported as their own failure group;
  - decoys in production: yes, same code path as the eval;
  - identity and count as separate metric rows (`line_present` and `line_quantity`).
- The review also caught an overclaim. The organiser question said the agent "re-runs async"; nothing did. There is now a "Retry AI check" button that re-checks the stored photos as a new linked record and flags disagreement with a hand decision, and the docs say plainly that it can't recall a box that has already shipped.

- **Gap check against the field.** Looked at what the other public forks of this track had built, to find missing features. Ideas only; no code was copied. Added from that review, each written from scratch:
  - an **uncertainty summary** on every unclear result: known / can't tell / what would settle it / next action;
  - **photo-reuse detection**: the same photo already used for another order can't seal a box;
  - a **daily AI-check cap** per organisation, so a public demo can't use up the API key;
  - a **download** of the exact hashed record;
  - **CI** that runs the isolation tests against a real Postgres;
  - a check that **both labellers finished before the agent ran**;
  - the template documents in this folder;
  - an **orders CSV import** page. Any organisation column in the file is ignored; orders always go to the signed-in organisation.
- The review also confirmed a few design choices. Several builds let the model decide, give it the order quantities, or treat "unsure" as "stop". This build does none of those.
- **UI redesign.** The first version worked but looked plain, and the phone layout was cramped. The new layout has stat cards, product tiles, a verdict banner with numbered fixes, and numbered boxes on the photo that match a found-items list. On phones there's a bottom tab bar, tappable rows, and a list instead of tables.
- **Photo-day tooling.** `eval/import_photos.py` groups phone photos into manifest boxes by capture time and writes a contact sheet to check the grouping. `catalogue/build_catalogue.py` turns a spreadsheet plus one folder per SKU into `catalogue.json`.
- **Privacy catch:** phone photos carry GPS location in EXIF, and the eval photos go into a public repository. Both tools save upright, resized copies with all EXIF removed.
- **HEIC** (iPhone default) is now accepted in the app and the tools.
- **Render blueprint** added. The web service gets only the restricted `pack_app` database role.
- Open: hosted Postgres and the Gemini key aren't set up yet, so the isolation tests against real Postgres and the first real model call haven't run. The dev and held-out photo sets are being shot today.

- **Backend connected** (evening). Neon Postgres (Singapore) and a Gemini key. The 7 isolation tests ran against real Postgres for the first time and passed. The first real model call worked end to end: about $0.002 and 1,900 tokens for one box.
  - It showed a UX flaw: long model descriptions were pasted mid-sentence into fix steps. The prompt now asks for a short phrase (prompt `pack-v2`).
  - It also showed that the web tests could reach the real model once a key was in `.env`. They now never do.
- **Full review, then fixes.** Two reviews read every module and confirmed each finding with a script. More than 40 confirmed bugs were fixed, each with a test (139 tests pass). The ones that mattered most:
  - **False-SEAL paths:** "packaging" the model wasn't sure of was ignored, even when it could have been a product under wrap. An object the model called packaging while naming a SKU lost that SKU. An unclear object whose alternative was the look-alike didn't raise `wrong_item`. All three now lead to a hand check.
  - **False STOPs:** an ordered SKU missing from the catalogue, or a model count with no object listed, read as "missing". Both are now UNCERTAIN.
  - **Evidence:** an override could re-hash an edited record and hide the edit. Overrides are now refused on a record that fails its hash. Each override keeps what it replaced, so every earlier version can be rebuilt and checked.
  - **Robustness:**
    - a tiny file claiming 20000×20000 pixels could exhaust server memory;
    - Enter in the note field recorded SEAL;
    - two operators deciding at once lost one decision;
    - a 2 MB+ CSV was silently cut;
    - an idle Neon connection would fail the first request.
  - **Our own tests** seeded dummy orders and left test rows in the live database. They now clean up after themselves.
- **Eval made harder to fool, ourselves included:**
  - a freeze file hashes photos, manifest, labels, catalogue, code and settings before the held-out run, and the run refuses to start if anything changed;
  - every headline rate carries a 95% interval, so "0 of 25" reads as "up to 13%";
  - the one-pager's kill conditions are checked automatically.
- **Output for other pods:** a CSV export whose first columns are exactly the organisers' `pack_sample.csv`, and `?since=` paging on the records API.
- **Sign-in page** redesigned: what the product does and what each result means, beside the form.

## Mon 28 Sep

- Read the handbook, all five track repositories and the Verity background documents. Wrote down 16 contradictions and gaps: [FINDINGS.md](../../FINDINGS.md). The ones that change the build:
  - `unit_id` means a whole box in Pack;
  - multipack quantities;
  - a lamp's cable collides with the cable sold on its own;
  - two decisions in the brief, but UNCERTAIN is "valid".
- Drafted questions for the organisers on UNCERTAIN, fail-open vs a seal gate, eval acceptance, scope, the contract names, and cost.
- **Key design choice:** the vision model only describes what's in the box, and deterministic rules decide. The model isn't told the order or the quantities, to avoid "the order says 2, so I see 2". Look-alikes and decoys are shown next to the ordered products.
- Built:
  - the agent: quality gate, one Gemini call per box, decision rules, evidence record with a content hash;
  - Postgres with forced row-level security;
  - the web app and read API;
  - eval tooling with two independent human labellers and the physical packing list as ground truth;
  - the evidence contract.
- **Sample replay:** with the organisers' `observed_in_box` as perfect perception, the rules stop all 4 wrong boxes. The human operator in the data sealed 2 of them.
- **Chose Gemini (free tier)** for cost, and because it returns bounding boxes. Responses are cached so eval re-runs don't spend quota. Free-tier prompts may be used by Google, so only the author's own product photos are used.

## Fri 25 Sep

- Build phase opened. Forked the repository.
