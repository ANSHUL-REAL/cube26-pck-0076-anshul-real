# LinkedIn post

Numbers are from the frozen held-out run in EVAL.md. Attach the walkthrough video as a native upload (a Drive link gets far less reach).

---

Would you tape this box shut? 📦

Small sellers ship the wrong item more often than they think: the red cap instead of the blue one, one towel short, a stray candle in the box. Nobody checks, and when the buyer says "wrong item", there's no proof either way.

For the CUBE Buildathon (Track 03) I built Pack Manager. The packer snaps the open box with any phone before sealing it. Our pack agent looks inside, lists every item it can see, and fixed rules check that list against the order. It gives one of three answers:

✅ Seal the box: everything ordered is there, nothing else is.
🛑 Stop and fix: exactly what to swap, add or remove, marked on the photo.
✋ Check by hand: when the photo can't settle it, it says what it can't see instead of guessing.

A few choices I'd make again:
→ The agent is never shown the order. It can't "see" 2 because the order says 2. It lists what's there, and plain rules decide.
→ "Not sure" is a real answer, counted on its own, not hidden inside an accuracy number.
→ Every box leaves a record: the photo, each check and why, and a hash that shows if the record was edited later. It even flags a photo reused for another order.
→ Companies can't see each other's data, enforced by Postgres row-level security and tested in CI.

Tested on real photos: one frozen run on 50 real warehouse photos (public Amazon Bin Image Dataset) it had never seen:
• Wrong boxes let through: 2 of 26
• Good boxes stopped: 12 of 24
• Sent to a person: 18 of 50
• The rules alone, given perfect perception: 0 errors

The honest part: a limit I set before the run was crossed. It stopped too many good boxes, mostly on cluttered, strapped bins it wrongly called "fully visible". So on photos like these it should keep the record and let a person decide, not block sealing. I published every miss.

No seller has used it yet. Talking to some is the next step.

Try it (one-click demo, no install): https://pack-manager-lzht.onrender.com
Walkthrough (73 s): https://drive.google.com/file/d/1XUA13bPx-OnsVwq6Aykgf4V1BOyiOFsN/view?usp=sharing
Code, eval and write-up: https://github.com/ANSHUL-REAL/cube26-pck-0076-anshul-real

Thanks @CodeQuesters and @Sydon.AI for the build-a-thon.

#CUBEBuildathon #BuildInPublic #Ecommerce #Logistics #ComputerVision #AIAgents
