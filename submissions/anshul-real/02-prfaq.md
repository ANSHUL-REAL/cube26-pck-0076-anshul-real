# PR/FAQ

## Press release (the future we're building towards)

**Pack Manager: small sellers can now prove what went in every box, using only a phone**

*Pune, 2027.* Sellers and 3PLs who pack their own orders can now check every box before it's taped. They can also keep a photo record of what was sent, without buying a camera station.

The packer photographs the open box with any phone. Within a few seconds Pack Manager says **Seal**, **Stop and fix** (with exactly what to swap, add or remove), or **Check by hand** (with exactly what it couldn't see). Every box gets an evidence record: the order, the photos, what was found, each check and why. When a buyer later says "wrong item" or "empty box", the seller has a timestamped photo of that box at sealing instead of their word.

Large distribution centres have had this for years, from vendors who sell fixed stations. Pack Manager is for the operations those vendors don't call on: a seller with folding tables and six packers.

"We used to lose an argument every time a buyer said the box was empty," said a (hypothetical) 3PL owner. "Now we send the photo."

## FAQ: customers

**Who is this for?**
Merchant-fulfilled sellers (Amazon MFN, Shopify, Walmart) and small 3PLs packing for them. It isn't for fully FBA sellers, because Amazon packs those boxes.

**What does it check?**
Every order line is present, each line has the right quantity, there's no wrong item (including a look-alike colour or size), and nothing extra. Packing slips, invoices and filler are ignored.

**What if it can't tell?**
It says **Check by hand** and lists what would settle it, for example "a count of the towels with every unit visible". It doesn't guess.

**What does it need from me?**
Your orders (CSV or JSON for now) and 2–3 reference photos per product, plus a phone.

**What if the AI is down?**
The photos and a record are still saved, marked "Needs your decision". Your packer checks by hand and carries on. Nothing waits on the AI.

**Can my clients see each other's boxes?**
No. Each organisation's data is separated by the database itself (row-level security, enforced and tested), including the photos.

## FAQ: the questions we'd rather not answer

**Does it actually work?**
We don't know yet. The rules have been tested thoroughly: 24 decision tests, and a replay of the organisers' sample where they stop 4 of 4 wrong boxes. Whether the vision model identifies look-alike products and counts stacked items reliably on real photos is what the held-out eval measures. If the false-SEAL rate is above 5% while it rarely says "check by hand", we'll say it shouldn't gate sealing.

**Isn't "Check by hand" just a way to avoid being wrong?**
It can be. That's why the UNCERTAIN rate is reported separately, split by good and bad boxes, and why the kill condition caps it at 25%. An agent that says "check by hand" on every box is useless, and the numbers will show that.

**Why would anyone pay for this if the three funded competitors exist?**
Maybe they won't. Our bet is that the competitors' customers (large DCs with fixed stations) are a different segment from sellers with no station. Nobody has asked a real seller yet, and that is the first thing to do after the build.

**What does each check cost, and who pays when it's wrong?**
One model call per box. Cost per box is measured in the eval against a $0.008 budget. A false SEAL (a wrong box let through) costs the seller a mis-ship. We report that error first and never blend it into a single "accuracy" number.

**Can a packer cheat it?**
Partly. Uploading a photo that was already used for another order is caught. Taking a new photo of a different, correct box isn't. The photo proves what was in *a* box at that moment, not that it was *this* box, unless the photo shows the shipping label. We don't claim more.

**Is the record tamper-proof?**
No. It has a content hash that shows whether a record was edited after it was saved, and every override keeps the previous hash. Someone with database access could rewrite a record and its hash together. It isn't a hash chain or anchored anywhere.

**What can't it see?**
Anything inside sealed retail packaging (a missing scoop inside a sealed protein tub), and items hidden under other items or filler unless it's told to look. Hidden items make it say "check by hand".

**What about privacy?**
Only box photos and product descriptions are sent to the model. The free Gemini tier used during the build may use prompts to improve Google's products, so only the builder's own household products were photographed. Production would use a paid tier. Photos are stored with their location data (EXIF/GPS) removed.
