# One-pager

**Problem.** Merchant-fulfilled sellers and small 3PLs mis-ship: missing items, wrong colour or size, wrong quantity, extras. Each one costs a refund, a return, a reshipment and often a review. Nobody checks, because checking every box by hand costs more than the mis-ships. When a buyer disputes, the seller has no proof of what was sent.

**Customer.** A seller or 3PL packing its own orders at tables, with phones and no camera station. Not fully FBA sellers.

**Solution.** Photograph the open box. One vision-model call lists what's in it, without being told the order. Deterministic rules compare that with the order and return **Seal**, **Stop and fix** (exact fixes) or **Check by hand** (what would settle it). Every box gets an evidence record with photos, checks, the decision, overrides and a content hash. The Returns and Recovery tracks can read it.

**Why now / why this way.** General vision models can compare an open box against reference photos without per-product training. The known order turns open-ended recognition into checking against a list, plus spotting anything that doesn't belong.

## Metrics

Measured on a held-out set of real boxes against what was physically packed. Every error type is reported separately.

| Metric | Why it matters | Target | Kill if |
|---|---|---|---|
| **False-SEAL rate** (bad boxes sealed ÷ bad boxes) | A mis-ship let through; the error that costs money | ≤ 2% | **> 5% while UNCERTAIN ≤ 25%** |
| False-STOP rate (good boxes stopped ÷ good boxes) | Slows the line; operators stop trusting it | ≤ 5% | > 15% |
| UNCERTAIN rate | Hand checks cost time; too many make it pointless | ≤ 25% | > 40% |
| Per-check false negatives / false positives | Which check fails, and how | reported | — |
| Human-vs-human kappa (2 labellers, photos only) | How hard the task is from a photo | reported | — |
| Agent vs human consensus kappa | Is the agent as good as a careful person | ≥ 0.7 | — |
| p95 latency per box | "Don't slow my line down" | ≤ 5 s | > 10 s |
| Cost per box | Pack touches every order | ≤ $0.008 | > $0.02 |

## Kill condition

If the held-out false-SEAL rate is **above 5% while UNCERTAIN is 25% or lower**, Pack Manager must not gate sealing. It runs only as an evidence recorder: photo plus record, no verdict. That alone still answers "what did you send?".

## Biggest risks

1. Look-alike variants (colour, size) that aren't visible in the photo. The mitigation is UNCERTAIN plus a hand check. Measured.
2. Stacked identical items. Mitigations: UNCERTAIN, a second photo, and "spread them out". Measured.
3. No real customer has confirmed they'd pay. That's the first thing to test after the build.
