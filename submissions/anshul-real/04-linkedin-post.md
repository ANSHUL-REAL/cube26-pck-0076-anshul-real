# LinkedIn post (draft)

Fill in the `[brackets]` from EVAL.md after the held-out run, and add the live URL and repo link. Keep the numbers even if they aren't flattering. Attach the demo video or 2–3 screenshots (the result page for a Stop and fix is the clearest).

---

Small sellers ship the wrong item more often than they think: the red cap instead of the blue one, one towel short, a stray cable in the box. Nobody checks, and when the buyer says "wrong item", there's no proof either way.

For the CUBE Buildathon (Track 03) I built **Pack Manager**. The packer photographs the open box with any phone before sealing it, and gets one of three answers:

• **Seal the box**: everything ordered is there, nothing else is.
• **Stop and fix**: exactly what to swap, add or remove, with numbered boxes on the photo.
• **Check by hand**: when the photo can't settle it (stacked items, a look-alike with its label hidden), it says what it can't see instead of guessing.

A few choices I'd make again:
• **The vision model only lists what it sees. Plain rules decide.** The model is never told the order, so it can't "see" 2 because the order says 2.
• **"Check by hand" is a real answer**, reported separately, not hidden inside an accuracy number.
• **Every box gets an evidence record**: photos, each check and why, and a content hash that shows if the record was edited later.
• **Companies can't see each other's data**, enforced by the database (Postgres row-level security) and tested in CI.

How it did on [N] real boxes it never saw during tuning, scored against what was physically packed and labelled by two people independently:
• Wrong boxes let through (false seal): [X]%
• Correct boxes stopped (false stop): [Y]%
• Sent to a hand check: [Z]%
[One honest sentence about the biggest failure mode, e.g. "Stacked towels are its weak spot."]

What it can't do: see inside sealed packaging, or tell look-alikes apart when the deciding detail is hidden. No seller has used it yet; talking to some is the next step.

Try it: [live URL] (demo codes on the sign-in page)
Code, eval and write-up: [repo URL]

Thanks @CodeQuesters and @Sydon.AI for the build-a-thon.

#CUBEBuildathon #BuildInPublic #Ecommerce #Logistics #ComputerVision
