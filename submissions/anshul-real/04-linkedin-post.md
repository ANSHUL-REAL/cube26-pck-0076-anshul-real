# LinkedIn post

Follows the organisers' Round 2 post guide (track, problem, how it works, engineering, learning, outcome, links, tags, official hashtags). Numbers are from the frozen held-out run in EVAL.md. Attach the walkthrough video as a native upload, and pick @CodeQuesters and @Sydon.AI from LinkedIn's tag dropdown.

---

Would you tape this box shut? 📦

For CUBE Buildathon Round 2, Track 03 (Pack Manager), I built Pack Manager: a pack agent that checks an open shipping box against its order before it's sealed, from one phone photo, and keeps the proof.

🔹 The problem
Small sellers ship the wrong item more often than they think: the blue cap instead of the red one, one towel short, a stray candle in the box. Nobody checks, and when a buyer says "wrong item", there's no proof either way.

🔹 What it does
The packer snaps the open box. The agent gives one of three answers:
✅ Seal the box: everything ordered is there, nothing else is.
🛑 Stop and fix: exactly what to swap, add or remove, marked on the photo.
✋ Check by hand: when the photo can't settle it, it says what it can't see instead of guessing.
Every box leaves a record (photo, each check and why, who did what) that Returns and Recovery can read later.

🔹 How it works
Photo → quality and reuse checks → the agent lists every item it sees, without ever being shown the order → fixed rules compare that list with the order → verdict + evidence record. The agent can't "see" 2 because the order says 2.

🔹 Engineering
FastAPI + Postgres with row-level security, so companies can't see each other's data (tested in CI). Gemini 3.5 Flash-Lite for vision, deterministic rules for the decision, a versioned evidence contract with a /v1 API for other teams, 181 tests, deployed on Render.

🔹 Key learning
I set a kill condition before testing. It tripped. Every error came from what the model saw, not from the rules: it called cluttered, strapped bins "fully visible" and missed items. So on photos like these, the honest design is "keep the record, let a person decide", not "block sealing". I published every miss.

🔹 Outcome
One frozen run on 50 real warehouse photos (public Amazon Bin Image Dataset) it had never seen:
• Wrong boxes let through: 2 of 26
• Good boxes stopped: 12 of 24
• Sent to a person: 18 of 50
• Rules alone, with perfect perception: 0 errors
Anyone can re-check these numbers from the repo in under a minute, no API key needed.

🎥 Demo: https://drive.google.com/file/d/1XUA13bPx-OnsVwq6Aykgf4V1BOyiOFsN/view?usp=sharing
💻 GitHub: https://github.com/ANSHUL-REAL/cube26-pck-0076-anshul-real
🌐 Live (one-click demo, no install): https://pack-manager-lzht.onrender.com

Thank you @CodeQuesters and @Sydon.AI for a brief that asked for proof, not just a demo. 🙌

#CubeBuildathon #CUBE #SydonAI #CodeQuesters #AIBuilders #AIEngineering #AgenticAI #AIHackathon #BuildWithAI #AIInnovation #Hackathon2026 #BuildInPublic
