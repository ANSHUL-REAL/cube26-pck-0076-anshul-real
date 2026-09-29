# Build log

Newest first. Decisions, what changed, and what's still open. Dates are IST.

## Tue 29 Sep

- **UI redesign.** The first version worked but looked plain, and the phone layout was cramped. The new layout has stat cards, product tiles, a verdict banner with numbered fixes, and numbered boxes on the photo that match a found-items list. On phones there's a bottom tab bar, tappable rows, and a list instead of tables.
- **Photo-day tooling.** `eval/import_photos.py` groups phone photos into manifest boxes by capture time and writes a contact sheet to check the grouping. `catalogue/build_catalogue.py` turns a spreadsheet plus one folder per SKU into `catalogue.json`.
- **Privacy catch:** phone photos carry GPS location in EXIF, and the eval photos go into a public repository. Both tools save upright, resized copies with all EXIF removed.
- **HEIC** (iPhone default) is now accepted in the app and the tools.
- **Render blueprint** added. The web service gets only the restricted `pack_app` database role.
- Open: hosted Postgres and the Gemini key aren't set up yet, so the isolation tests against real Postgres and the first real model call haven't run. The dev and held-out photo sets are being shot today.

## Mon 28 Sep

- Read the handbook, all five track repositories and the Verity background documents. Wrote down 16 contradictions and gaps: [FINDINGS.md](../FINDINGS.md). The ones that change the build:
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
