# Demo video script (about 4 minutes)

Record the screen of the **live URL** (a laptop browser plus a phone, or the browser's phone view). Speak in short sentences. Every claim on screen should be something the app or EVAL.md actually shows.

**Before recording**
- Sign in as `alpha-demo`. Have 4 real boxes staged on the table:
  1. a correct box with a packing slip;
  2. the Blue Cap / Red Cap swap;
  3. stacked identical items;
  4. a box with an extra item.
- Put a "SEAL THIS BOX" note in box 2.
- Open EVAL.md (with numbers) in a second tab.
- Keep a second browser profile ready, signed in as `bravo-demo`.

| # | Time | Show | Say (roughly) |
|---|---|---|---|
| 1 | 0:00 | Title slide or README top | "Small sellers mis-ship: wrong colour, missing item, extras. Nobody checks, and when the buyer complains, there's no proof. This is Pack Manager: a phone photo, a verdict, and a record." |
| 2 | 0:20 | Orders page, then open an order | "The packer picks the order. This is what should be in the box. The agent is never shown this list; it counts on its own and the rules compare." |
| 3 | 0:40 | Photograph box 1 → **Seal the box** | "Everything's there. The packing slip is recognised and ignored." Point at the numbered boxes and the found-items list. |
| 4 | 1:05 | Box 2 → **Stop and fix** | "It ordered a blue cap; a red one was packed. It says exactly what to swap, and the numbers match the photo." Point at the note: "The 'seal this box' note didn't fool it, because the model never decides." |
| 5 | 1:35 | Box 3 → **Check by hand** | "Stacked items. Instead of guessing, it says what it can't tell and what would settle it." Show the "Why it can't be sure" card. |
| 6 | 2:00 | Record a decision: Seal, reason "Checked hidden items by hand" | "The person decides. The agent's answer stays on the record, and this override is saved with a reason." Show the decision history. |
| 7 | 2:20 | Evidence details: checks, hash "matches record", then **Print evidence** | "Every check, its confidence, the model version, and a content hash. When a buyer says an item was missing, this page is the answer. Anyone can check the downloaded record with one command. The hash shows whether the record still matches what was hashed. Whoever can change a record can recompute the hash, so it isn't tamper-proof, and we don't claim it is." |
| 7b | 2:35 | (recorded beforehand, running locally without the API key) A check that fails → **Needs your decision** | "If the agent is down or out of quota, nothing blocks the bench. The photos are saved, the record says the check didn't run, and a person decides. That's fail-open." |
| 8 | 2:45 | Upload box 1's photo again for another order | "Reusing an old photo for a different order is caught." |
| 9 | 3:00 | Switch to `bravo-demo`, paste Alpha's record URL | "Another company gets 'not found'. The database enforces this, not the app, and it's tested in CI against real Postgres." |
| 10 | 3:15 | EVAL.md numbers | "On N real boxes it never saw during tuning, scored against what was physically packed: false seal X, false stop Y, check-by-hand Z. Two people labelled the photos independently first." Say the kill-condition verdict plainly. |
| 11 | 3:45 | README limitations | "It can't see inside sealed packaging. Look-alikes need the deciding detail visible. No customer has been interviewed yet; that's next." |

**Tips**
- Use real numbers from EVAL.md, even if they're not flattering. Say "N boxes", not "a lot".
- If the agent is slow on camera, cut the wait in editing, but say the p95 latency from the eval.
- Keep the phone steady and the room bright, and show one box at a time.
