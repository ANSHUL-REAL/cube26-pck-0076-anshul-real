# CLAUDE.md: durable constraints for anyone (human or AI) changing this project

## What this is

Pack Manager checks an open outbound box against its order before sealing, and leaves an evidence record. It is Track 03 of a five-agent chain (Receiving, Prep, Pack, Returns, Recovery). Code is at the repository root: `pack_manager/` (agent), `app/` (web), `db/` (schema), `eval/`, `contract/`.

## Hard rules (don't break these, even to make a demo work)

1. **The model perceives, code decides.** The vision model never outputs SEAL / STOP_AND_FIX / UNCERTAIN. `pack_manager/decision.py` decides from its object list.
2. **The model is never told the order or the quantities** in production. `--reveal-order` exists only as an eval ablation.
3. **One model call per box**, carrying every check (engineering rule 2). Never one call per check or per item.
4. **Fail open.** A model error, timeout or quota limit still saves the photos and a record with status `pending`. Nothing blocks the operator.
5. **UNCERTAIN is a real outcome**, never a low-confidence SEAL. A photo that failed the quality gate can never lead to SEAL.
6. **Tenancy before features.** Every tenant table has RLS **enabled and forced**. The app role is not the owner, not a superuser and has no BYPASSRLS. `app.org_id` is set per transaction. Photos stay in the RLS table, addressed by random UUID. Never add a code path that takes the organisation from the request instead of the session or access code.
7. **Overrides are data.** An operator decision is appended with the original decision, the reason code and the prior hash. The agent's checks are never edited or removed.
8. **Authoritative sources only.** Expected contents come from the order store. Never infer them from the model, from photos, or from the sample CSVs. The sample CSVs are dummy data.
9. **Records follow the organisers' Evidence Contract 1.1.** `pack_manager/contract.py` writes it; `/v1` serves it. Don't rename, remove or repurpose its fields or our published check keys; add only under `checks[].detail`. If you change the record, run `python contract/build_contract.py` and keep `tests/test_contract.py` and `tests/test_contract11.py` green.
10. **No secrets in the repo.** `.env` stays git-ignored. Photos committed to the repo must have EXIF (GPS) stripped: use `eval/import_photos.py` and `catalogue/build_catalogue.py`.
11. **Held-out means held out.** Never tune prompts or thresholds on the `test` split. Anything changed after seeing test results is reported as "tuned on the eval set, not held-out".

## Forbidden language (in docs, UI, demo and posts)

| Don't say | Say instead |
|---|---|
| "tamper-proof", "immutable", "blockchain", "anchored", "audit-grade" | "content hash: shows whether a record still matches what was hashed" (Evidence Contract 1.1: never "tamper-evident") |
| "accurate", "reliable", "works well" without a number | the measured number, with n, the method and FP/FN separately |
| "detects everything", "guarantees" | what it checks, and what it can't see (sealed packaging, hidden items) |
| "AI decides" | "the model lists what it sees; rules decide" |
| "customers want this", "validated" | "hypothesis; no customer interviewed yet" |
| a single blended "accuracy %" | false-SEAL, false-STOP and UNCERTAIN rates, separately |

## How to work here

- Run `python -m pytest` before every commit. The isolation tests need Postgres (CI provides one).
- UI: calm and friendly, with nothing unnecessary and no neon or glow. Check it on a 375 px phone width.
- User-facing text: short plain sentences. Refer to items by the number drawn on the photo (#1, #2).
