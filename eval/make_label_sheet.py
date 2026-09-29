"""Build a single self-contained HTML page for the human labellers.

    python eval/make_label_sheet.py --split test

Creates eval/label_sheet_test.html. Send that one file to each labeller (it works offline,
on a phone or laptop). For each box it shows ONLY the order and the photos the agent is
sent (the first max_box_photos), never the scenario or the real contents. Each labeller
types their name, picks Seal / Stop and fix / Can't tell, then taps "Download my labels",
and the CSV goes into eval/labels/. Answers are kept in the browser under the name typed,
so two labellers sharing one device never see or download each other's answers.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json

from common import EVAL_DIR, ORG, ROOT, eval_settings, load_manifest
from PIL import Image, ImageOps

from pack_manager.catalogue import load_org_catalogue


def thumb(path, max_side=1100) -> str:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Label the boxes</title>
<style>
body{margin:0;background:#f6f6f3;color:#1f2328;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:16px}
.card{background:#fff;border:1px solid #e3e3de;border-radius:12px;padding:16px;margin:14px 0}
h1{font-size:22px;margin:4px 0}h2{font-size:17px;margin:0 0 6px}
.muted{color:#62666d}.small{font-size:13px}
img{width:100%;border-radius:8px;margin-top:8px;display:block}
.opts{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.opts label{flex:1;min-width:120px;border:1px solid #e3e3de;border-radius:10px;padding:10px;text-align:center;cursor:pointer;font-weight:600}
.opts input{display:none}
.opts label:has(input:disabled){opacity:.5;cursor:not-allowed}
.opts input:checked+span.seal{color:#1e6b40}.opts label:has(input:checked){border-color:#1f2328;background:#f6f6f3}
input[type=text]{font:inherit;width:100%;padding:9px 11px;border:1px solid #e3e3de;border-radius:10px;margin-top:8px;box-sizing:border-box}
.bar{position:sticky;bottom:0;background:#fff;border-top:1px solid #e3e3de;padding:12px 16px;display:flex;gap:12px;align-items:center;justify-content:space-between}
button{font:inherit;font-weight:600;border:0;background:#2f5d8a;color:#fff;padding:10px 16px;border-radius:10px;cursor:pointer}
ul{margin:4px 0 0;padding-left:20px}
</style></head><body>
<div class="wrap">
  <h1>Label the boxes</h1>
  <p class="muted">For each box, look only at the photos and the order. Choose <b>Seal</b> if the box holds exactly the order, <b>Stop and fix</b> if something is missing, wrong or extra, or <b>Can't tell</b> if the photos don't let you decide. Please don't discuss answers with the other labeller.</p>
  <div class="card"><label>Your name <input type="text" id="who" placeholder="e.g. Rahul" autocomplete="off"></label>
    <p class="muted small">Type your name first: the choices unlock once you do. Your answers are saved in this browser under your name. If someone else labels on this device, they type their own name and start with an empty sheet.</p></div>
  __BOXES__
</div>
<div class="bar"><span id="progress" class="muted small"></span><button id="dl" type="button">Download my labels</button></div>
<script>
const BOXES = __IDS__;
const SPLIT = "__SPLIT__";
// One saved sheet per labeller name, so people sharing a browser never mix answers.
const keyFor = name => `pack-labels-${SPLIT}-${name.toLowerCase()}`;
function load(name){
  try {
    const saved = localStorage.getItem(keyFor(name));
    if (saved) return JSON.parse(saved);
    // An older version of this page kept one sheet per split: reuse it only for the same name.
    const old = JSON.parse(localStorage.getItem(`pack-labels-${SPLIT}`) || "{}");
    return (old._who || "").trim().toLowerCase() === name.toLowerCase() ? old : {};
  } catch(e){ return {}; }
}
function save(){ if (who) { try { localStorage.setItem(keyFor(who), JSON.stringify(state)); } catch(e){} } }
let who = document.getElementById("who").value.trim();
let state = who ? load(who) : {};
function progress(){ const done = BOXES.filter(id => state[id] && state[id].d).length;
  document.getElementById("progress").textContent = who ? `${who}: ${done} of ${BOXES.length} labelled`
                                                        : "Type your name at the top to start"; }
function show(){
  for (const id of BOXES) {
    const v = state[id] || {};
    for (const el of document.getElementsByName(`d_${id}`)) { el.checked = el.value === v.d; el.disabled = !who; }
    const note = document.getElementById(`n_${id}`);
    note.value = v.n || ""; note.disabled = !who;
  }
  progress();
}
document.getElementById("who").addEventListener("input", e => {
  who = e.target.value.trim(); state = who ? load(who) : {}; show();
});
document.addEventListener("change", e => {
  if (!who || e.target.id === "who") return;
  const m = e.target.name && e.target.name.match(/^d_(.+)$/);
  if (m) state[m[1]] = {...(state[m[1]]||{}), d: e.target.value, t: new Date().toISOString()};
  const n = e.target.id && e.target.id.match(/^n_(.+)$/);
  if (n) state[n[1]] = {...(state[n[1]]||{}), n: e.target.value};
  save(); progress();
});
document.getElementById("dl").onclick = () => {
  if (!who) { alert("Please type your name at the top first."); return; }
  const q = s => '"' + String(s || "").replace(/"/g, '""') + '"';
  let csv = "labeller,box_id,decision,note,labelled_at\\n";
  for (const id of BOXES) if (state[id] && state[id].d) csv += [q(who), q(id), q(state[id].d), q(state[id].n), q(state[id].t)].join(",") + "\\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], {type: "text/csv"}));
  a.download = `labels_${who.replace(/[^a-z0-9]+/gi, "_")}.csv`; a.click();
};
show();
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    args = ap.parse_args()
    settings = eval_settings()
    catalogue, _ = load_org_catalogue(ROOT / settings.catalogue_dir, ORG)
    boxes = [b for b in load_manifest(args.split) if b.photos]

    cards = []
    for n, box in enumerate(boxes, 1):
        items = "".join(
            f"<li>{q} × {html.escape(catalogue.title(sku))}"
            + (f" <span class='muted small'>({html.escape(', '.join(catalogue.get(sku).attributes.values()))})</span>"
               if catalogue.get(sku) and catalogue.get(sku).attributes else "")
            + "</li>"
            for sku, q in box.expected.items()
        )
        # Exactly the photos run_eval.py sends the agent, so humans and agent see the same box.
        photos = "".join(f'<img loading="lazy" src="{thumb(p)}" alt="Box photo">'
                         for p in box.photos[: settings.max_box_photos])
        bid = html.escape(box.box_id)
        opts = "".join(
            f'<label><input type="radio" name="d_{bid}" value="{v}"><span>{t}</span></label>'
            for v, t in [("SEAL", "Seal"), ("STOP_AND_FIX", "Stop and fix"), ("UNCERTAIN", "Can't tell")]
        )
        cards.append(
            f'<div class="card"><h2>Box {n} <span class="muted small">({bid})</span></h2>'
            f'<div class="muted small">The order says the box should contain:</div><ul>{items}</ul>{photos}'
            f'<div class="opts">{opts}</div>'
            f'<input type="text" id="n_{bid}" placeholder="Note (optional): what did you see?"></div>'
        )
    page = (PAGE.replace("__BOXES__", "\n".join(cards))
                .replace("__IDS__", json.dumps([b.box_id for b in boxes]))
                .replace("__SPLIT__", args.split))
    out = EVAL_DIR / f"label_sheet_{args.split}.html"
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} with {len(boxes)} boxes ({out.stat().st_size / 1e6:.1f} MB). Send this file to each labeller.")


if __name__ == "__main__":
    main()
