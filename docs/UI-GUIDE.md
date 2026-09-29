# UI guide

How the web app looks, where the patterns came from, and how to keep it consistent. Everything lives in two places: [`app/static/app.css`](../app/static/app.css) (one stylesheet, no build step) and the Jinja templates in [`app/templates/`](../app/templates/).

## Where the patterns come from

| Pattern | Borrowed from | Used on |
|---|---|---|
| List page: title and a secondary action on top, then one card with filter tabs, search and a table of rows with status badges | [Shopify admin (Polaris)](https://polaris.shopify.com/), the admin most small sellers already use daily | Orders, Records |
| Detail page: main column for the task, side column for facts about the object | Shopify order details | Order page, result page |
| One record per box: what was detected with counts, a pass/fail status, and a timeline of events | [Rabot](https://rabot.us/) pack-station records | Result page ("What the camera saw", History) |
| Find proof by order ID and send a link to it | [vAudit](https://vaudit.ai/) ("search by order or return ID", shareable links) | Records search, "Copy link" |
| Tell the packer right away when a box is incomplete or has the wrong quantity | [Vimaan PackVIEW](https://vimaan.ai/inventory-tracking-products/packview/) | Result banner with numbered fixes |

Those products use fixed cameras at a station. This app is the same record, taken with a phone.

## Design tokens

All colours, radii, shadows and fonts are CSS variables at the top of `app.css`. Change a token, not individual rules.

| Token | Value | Use |
|---|---|---|
| `--bg` | ivory `#f6f5f2` | Page background |
| `--surface` | white | Cards |
| `--brand` | deep blue `#1f4f8f` | Primary buttons, active tab, links, focus ring. Nothing else. |
| `--seal` / `--stop` / `--unsure` / `--pending` | green / red / amber / grey, each with `-soft`, `-line` and `-mark` | Only for results. Never for decoration. |
| `--display` | Instrument Serif | Page titles, the result word, the summary counts |
| `--font` | Instrument Sans | Everything else, including numbers in tables |
| `--radius` | 14px (cards), 10px (buttons, inputs) | |

## Components

| Class | What it is |
|---|---|
| `.page-head`, `.title-row`, `.facts`, `.actions` | Page title, status badge next to it, a dotted facts line, buttons on the right |
| `.summary` | One strip of counts with a coloured dot per result |
| `.card.index` + `.index-bar` + `.table .tr` | List card: tabs and search in the bar, rows as a CSS grid. The first column holds a `.stretch` link so the whole row is clickable. |
| `.layout.verify-layout`, `.layout.record-layout` | Two columns on desktop. On phones, the order contents come before the photo. |
| `.badge.<tone>` | A dot and a word. Tones: `seal`, `stop`, `unsure`, `pending`, `plain` |
| `.verdict.<tone>` | Result banner: the result word, the reason, numbered fixes, the check tally |
| `.checklist`, `.tally` | Ordered vs found, one row per SKU |
| `.events` | History timeline |
| `.kv` | Label and value pairs in a side card |
| `.fold` | Collapsible card for detail most people skip |
| `.callout.<error/warn/info>` | Inline messages. Colour only, no icon. |

## Rules

1. **Colour means something.** Green, red and amber appear only for seal, stop and check by hand. The brand blue is for actions.
2. **No emojis, and no decorative icons.** Icons are allowed only for the logo, search, back arrows, row arrows and fold chevrons.
3. **Words over symbols.** "Not checked", "Check by hand", "3 checks passed". Refer to items by the number drawn on the photo (#1, #2).
4. **One primary button per screen.** Everything else is `.btn.secondary`.
5. **Phones first for packers.** Check every page at 375px wide: nothing may scroll sideways, and the main action must be reachable without zooming. Navigation moves to the bottom tab bar.
6. **Language rules** from [CLAUDE.md](../submissions/anshul-real/CLAUDE.md) apply to UI text: no "tamper-proof", no single "accuracy %".

## Checking a change

```bash
python -m pytest tests/test_pages.py
```

Then open the app, sign in with a demo code, and look at: Orders (each tab), an order page, a result page for each outcome, Records (search and filter), Import, and sign-in. Check them on desktop and at phone width. CSS and JS links carry a version number, so phones pick up changes after a deploy.
