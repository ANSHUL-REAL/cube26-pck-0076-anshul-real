# LinkedIn post

Follows the organisers' Round 2 post guide (track, problem, how it works, engineering, learning, outcome, links, tags, official hashtags). Numbers are from the frozen held-out run in EVAL.md. Attach the walkthrough video as a native upload, and pick @CodeQuesters and @Sydon.AI from LinkedIn's tag dropdown.

---

4 boxes in the organisers' sample data had the wrong items inside.
The packer sealed 2 of them. My agent's decision rules stopped all 4. 📦

That's the job I took on for CUBE Buildathon Round 2, Track 03 (Pack Manager): check every box before the tape goes on, and keep proof of what was sent.

Meet Pack Manager 👇

📸 Snap the open box with any phone. Our pack agent gives one of three answers:
✅ Seal it: everything ordered is there, nothing else.
🛑 Stop and fix: "Replace Red Cap (#3) with Blue Cap", marked on the photo.
✋ Check by hand: when the photo can't settle it, it says what it can't see instead of guessing.

Every box leaves a record: the photo, each check and why, who did what. So when a buyer says "wrong item", the seller has proof, and the Returns and Recovery teams can read it.

🧠 The design choice I'm proudest of
The agent is never shown the order. It only lists what's in the box, and fixed rules compare that list with the order.
It can't "see" 2 just because the order says 2, and every verdict can be explained check by check.

⚙️ Under the hood
Gemini 3.5 Flash-Lite (one vision call per box) · FastAPI · Postgres with row-level security, so companies never see each other's data · a versioned evidence API other teams can read · 181 tests · live on Render

📊 The honest part
I tested it once, frozen in advance, on 50 real warehouse photos it had never seen (public Amazon Bin Image Dataset):
• Wrong boxes let through: 2 of 26
• Good boxes stopped: 12 of 24 ← not good enough yet
• Sent to a person: 18 of 50
• The rules alone, given perfect perception: 0 errors

A limit I set before the test was crossed. Every error came from what the model saw, not from the rules: on cluttered, strapped bins it said "fully visible" and missed items.
So on photos like these it shouldn't block sealing. It should keep the record and let a person decide. Every miss is published, and anyone can re-check the numbers from the repo in a minute, no API key needed.

My biggest learning: a number you can reproduce beats a number that looks good.

🎥 73-second walkthrough on a phone (attached): https://drive.google.com/file/d/1XUA13bPx-OnsVwq6Aykgf4V1BOyiOFsN/view?usp=sharing
🌐 Try it, one-click demo, no install: https://pack-manager-lzht.onrender.com
💻 Code, eval and write-up: https://github.com/ANSHUL-REAL/cube26-pck-0076-anshul-real

Thank you @CodeQuesters and @Sydon.AI for a brief that asked for proof, not just a demo. 🙌

#CubeBuildathon #CUBE #SydonAI #CodeQuesters #AIBuilders #AIEngineering #AgenticAI #AIHackathon #BuildWithAI #AIInnovation #Hackathon2026 #BuildInPublic
