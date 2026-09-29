# Customer letter

> **This is a hypothesis, not a real customer.** No seller or 3PL has been interviewed yet. It was written by the builder to state what we believe a customer would say, so that each belief can be tested. The background documents contain only a synthetic prep-centre voice and nothing from a merchant-fulfilled seller.

---

To whoever is building the box checker,

I run a small 3PL out of a 6,000 sq ft unit on the edge of Pune. We pack for eleven online sellers: Shopify stores, a few Amazon merchant-fulfilled accounts and one Walmart seller. On a normal day that's 350 to 600 boxes, packed by six people at folding tables. We don't have a pack station with a camera over it, and I'm not buying one.

Here's what actually costs me money. It isn't the wrong box itself. It's what happens after:

- A buyer says the box arrived empty, or had the wrong colour, or one mug instead of two. My client refunds them and then asks **me** to prove what we sent. I have nothing except my packer's word, and she packed 400 boxes that day.
- One of my clients sells caps in six colours that look the same under our tube lights. Blue and navy get swapped maybe twice a week. Each one costs a refund, a return label and a reshipment, and sometimes a one-star review that mentions us by name.
- When a mistake happens, the client doesn't just want it fixed. They want to know it won't happen again. I can't show them anything.

What I'd pay for:

1. **Proof, first.** A photo of every open box at the moment it was sealed, with the order next to it and a time on it, that I can send to a client or attach to a dispute. Even if the checking wasn't perfect, the proof alone is worth something to me.
2. **A second pair of eyes that doesn't slow us down.** My packers will ignore anything that makes them wait. If it takes more than a few seconds, or stops them for no reason more than a couple of times a day, they will find a way around it by Friday.
3. **Honesty when it can't tell.** If the towels are stacked and it can't count them, I'd rather it say "check this one by hand" than guess. One confident wrong answer and my team stops trusting it.
4. **My clients can't see each other.** Client A must never be able to see client B's orders or photos. That's a contract term for me, not a nice-to-have.

What I won't do: buy hardware, retrain my team for a week, or pay per check more than a box of tape costs me per day.

If you can give me the photo proof on every box and catch the swaps, I'll try it on one client's orders for a month.

— A (hypothetical) 3PL owner

---

## What we take from it, and how we'd test it

| Belief | How the build answers it | How to test it with a real customer |
|---|---|---|
| Proof matters more than accuracy | Every box gets a record, even when the model fails (`pending`) | Ask: "Would you pay for the photo record alone, with no verdict?" |
| Speed or it gets bypassed | One model call per box, local photo check first, fail-open | Time 50 real boxes at their bench |
| "Check by hand" beats a wrong guess | UNCERTAIN is its own outcome, with what would settle it | Count how often they'd accept a hand check per day |
| Client separation is a hard requirement | Postgres RLS enabled and forced, tested with two organisations | Ask who else, at their clients, needs access |
| No hardware | A phone and a browser | Try it on their phones, in their light |
