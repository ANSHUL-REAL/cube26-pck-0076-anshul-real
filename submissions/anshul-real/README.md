# ANSHUL-REAL · Pack Manager

Anshul Nautiyal · CUBE Buildathon Round 2 · Track 03 (Pack Manager)

The code lives at the **repository root**, not in this folder, because the fork itself is the submission and the deployment builds from the root. This folder holds the documents the organisers' template asks for, and links to everything else.

| Deliverable | Where |
|---|---|
| Customer letter | [01-customer-letter.md](01-customer-letter.md) |
| PR/FAQ, including the questions we'd rather not answer | [02-prfaq.md](02-prfaq.md) |
| One-pager: metrics and kill condition | [03-one-pager.md](03-one-pager.md) |
| LinkedIn post draft (numbers filled in after the eval) | [04-linkedin-post.md](04-linkedin-post.md) |
| Durable constraints and forbidden language | [CLAUDE.md](CLAUDE.md) |
| Build brief | [build-brief.md](build-brief.md) |
| Build log | [build-log.md](build-log.md) |
| Eval report (method now, numbers after the held-out run) | [../../EVAL.md](../../EVAL.md) |
| Evidence contract for the other pods | [../../contract/](../../contract/README.md) |
| Agent code (headless first: `python -m pack_manager`) | [../../pack_manager/](../../pack_manager/) |
| Web app | [../../app/](../../app/) |
| Architecture, design decisions, threat model | [../../ARCHITECTURE.md](../../ARCHITECTURE.md) |
| Findings (contradictions in the brief and data) | [../../FINDINGS.md](../../FINDINGS.md) |

## Status

| Face | Deliverable | Status |
|---|---|---|
| 1 | Customer letter, PR/FAQ, one-pager | ☑ written (customer voice is a hypothesis, not an interview) |
| 2 | CLAUDE.md | ☑ |
| 3 | Headless agent on fixtures | ☑ CLI + organiser-sample replay (rules stop 4/4 wrong boxes; the operator stopped 2/4) |
| 4 | Eval report | ◐ method committed before data collection; held-out run pending |
| 5 | Evidence record page | ☑ web app record page, JSON API, content hash |
| 6 | Cross-pod contract | ☑ JSON Schema + example records |

## Kill condition

If the held-out **false-SEAL rate is above 5% while UNCERTAIN is 25% or lower**, the agent must not gate sealing. It should run only as an evidence recorder (photo + record, no verdict).
