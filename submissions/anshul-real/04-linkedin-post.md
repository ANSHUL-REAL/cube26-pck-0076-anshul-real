# LinkedIn post

Written for a general audience, and follows the organisers' Round 2 post guide (track, problem, how it works, engineering, learning, outcome, links, tags, official hashtags). Numbers are from the frozen held-out run in EVAL.md. Attach the walkthrough video as a native upload, and pick @CodeQuesters and @Sydon.AI from LinkedIn's tag dropdown.

---

Ever opened a package and found the wrong item inside? 📦

Usually, nobody checked the box before it was taped shut. Small online sellers pack orders by hand, and fast, so mistakes slip through: the red cap instead of the blue one, one towel short, something from another order. Then the buyer asks for a refund, and the seller can't prove what they actually sent.

So I built Pack Manager 👇

The packer takes one photo of the open box with their phone. Our pack agent looks at what's inside and gives one of three answers:
✅ Seal it: everything ordered is there, nothing extra.
🛑 Stop and fix: exactly what's wrong, like "Replace Red Cap (#3) with Blue Cap", marked on the photo.
✋ Check by hand: if the photo isn't clear enough, it says so instead of guessing.

Every box also keeps its photo as a receipt. If a buyer says "wrong item", the seller can show exactly what went in.

💡 The one idea that makes it trustworthy
The agent is never told what's supposed to be in the box. It just lists what it sees. Then simple, fixed rules compare that list with the order.
Why? Tell anyone "there should be 2 in there" and they're more likely to "see" 2. Keeping the two steps apart keeps the check honest, and every answer can be explained step by step.

📊 How well does it work? Honestly: not perfect yet.
A lot of AI projects are only tested on clean, made-up pictures. I tested on real photos: 50 real warehouse photos it had never seen, from a public Amazon dataset.
• Wrong boxes it would have let through: 2 of 26
• Correct boxes it stopped by mistake: 12 of 24
• Boxes it handed to a person to check: 18 of 50

I also tested it on 50 AI-generated box photos, kept separate. There it did far better (1 of 26 and 1 of 24), which is exactly why I don't count them: real life is messier.

That middle number is too high. Every mistake came from reading messy, cluttered photos, not from the rules. So today the right use is: keep a photo record of every box and let a person make the final call, rather than block packing. I published every miss, and anyone can re-check the numbers themselves.

The biggest thing I learned: an honest number you can check beats an impressive number you can't.

I built this solo for the CUBE Buildathon (Round 2, Pack Manager track) by @CodeQuesters and @Sydon.AI. Thank you for a challenge that asked for proof, not just a demo. 🙌

🎥 73-second walkthrough (video attached): https://drive.google.com/file/d/1XUA13bPx-OnsVwq6Aykgf4V1BOyiOFsN/view?usp=sharing
🌐 Try it yourself, one click, no sign-up: https://pack-manager-lzht.onrender.com
💻 For the techies (Python, a Gemini vision model, Postgres; code, tests and the full test write-up): https://github.com/ANSHUL-REAL/cube26-pck-0076-anshul-real

#CubeBuildathon #CUBE #SydonAI #CodeQuesters #AIBuilders #AIEngineering #AgenticAI #AIHackathon #BuildWithAI #AIInnovation #Hackathon2026 #BuildInPublic
