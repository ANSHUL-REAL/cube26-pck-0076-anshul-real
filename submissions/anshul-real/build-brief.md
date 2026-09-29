# Build brief

**Goal.** A working Pack Manager that a small seller could try at a real packing table, plus honest numbers on whether it should be trusted to gate sealing.

**In scope**
- Photo capture from any phone (1–3 photos per box), with a local quality check first.
- Checks: every order line present, the right quantity per line, no wrong item (including look-alike variants), nothing extra. Photo quality, whether the whole box is visible, and photo reuse.
- Outcomes: SEAL / STOP_AND_FIX / UNCERTAIN, with PENDING when the model fails. Fix instructions, and what would settle an unclear result.
- An evidence record in handbook field names, with a content hash, operator overrides as data, a read API for Returns and Recovery, and a JSON Schema contract.
- Tenancy: Postgres RLS enabled and forced, tested with two organisations.
- A held-out eval on real boxes: physical truth, two independent labellers, per-check FP/FN, and an ablation.

**Out of scope (stated as limitations)**
- Anything inside sealed retail packaging. Carton weight or dimensions. Barcode scanning.
- Live Shopify or Amazon integrations (orders are imported). Hardware auto-capture.
- Tamper-evident or anchored records (a content hash only).

**Key decisions** (details in [ARCHITECTURE.md](../../ARCHITECTURE.md))

| Decision | Because |
|---|---|
| The model describes and code decides | Deterministic, testable, explainable verdicts |
| Don't tell the model the order | Prevents "the order says 2, so I see 2" (ablated in the eval) |
| Look-alikes and decoys in every prompt | Forces a comparison instead of confirmation |
| Gemini (free tier), one call per box, cached | Cost; bounding boxes; eval re-runs are free |
| FastAPI + server-rendered HTML | Works on any phone browser, with no build step |
| Postgres with forced RLS, photos in the database | Isolation holds even for guessed photo IDs |

**Definition of done**
- `python -m pytest` passes, including the isolation tests against real Postgres (CI).
- A live URL where both demo organisations can check a box end to end.
- EVAL.md with held-out numbers, failure modes and the kill-condition verdict.
- A demo video, the README with setup, assumptions and limitations, and a LinkedIn post.

**Deadline.** Thu 1 Oct 2026, 18:00 IST (target: submitted by 14:00). No code commits after the build phase.
