"""Score a run against physical ground truth and the two human labellers.

    python eval/metrics.py --run test-v1

Writes eval/results/<run>/report.md and metrics.json.

Ground truth = what was physically packed (manifest actual_contents), not what a photo
shows. Human labels (eval/labels/*.csv) = what two people decided from the photos alone,
before the agent ran. Error types are always reported separately, never blended.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime

from common import EVAL_DIR, load_manifest

from pack_manager.models import EvidenceRecord

DECISIONS = ["SEAL", "STOP_AND_FIX", "UNCERTAIN"]


def cohen_kappa(a: list[str], b: list[str], labels: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    return 1.0 if pe == 1 else round((po - pe) / (1 - pe), 3)


def pct(num: int, den: int) -> str:
    return f"{num}/{den} ({num / den:.0%})" if den else "n/a"


LABEL_TIMES: dict[str, str] = {}  # labeller -> time of their last label (ISO, UTC)


def load_labels() -> dict[str, dict[str, str]]:
    """{labeller: {box_id: decision}} from eval/labels/*.csv. Also records each labeller's
    last labelled_at in LABEL_TIMES, to check the labels came before the agent ran."""
    out: dict[str, dict[str, str]] = {}
    for path in sorted((EVAL_DIR / "labels").glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                who = (r.get("labeller") or path.stem).strip()
                out.setdefault(who, {})[r["box_id"].strip()] = r["decision"].strip().upper()
                t = (r.get("labelled_at") or "").strip()
                if t:
                    LABEL_TIMES[who] = max(LABEL_TIMES.get(who, ""), t)
    return out


def labelled_before(names: list[str], started_at: str | None) -> str:
    if not started_at:
        return "unknown (run has no start time)"
    missing = [n for n in names if n not in LABEL_TIMES]
    if missing:
        return f"unknown ({', '.join(missing)}: no timestamps in the label file)"
    start = datetime.fromisoformat(started_at)
    late = [n for n in names if datetime.fromisoformat(LABEL_TIMES[n].replace("Z", "+00:00")) >= start]
    return f"NO: {', '.join(late)} labelled after the agent ran" if late else "yes"


def check_table(rows: list[tuple[str, str]]) -> dict:
    """rows of (truth PASS/FAIL, agent PASS/FAIL/UNCERTAIN). FAIL = a problem is present."""
    c = Counter(rows)
    tp, fn = c[("FAIL", "FAIL")], c[("FAIL", "PASS")]
    fp, tn = c[("PASS", "FAIL")], c[("PASS", "PASS")]
    unc_bad, unc_ok = c[("FAIL", "UNCERTAIN")], c[("PASS", "UNCERTAIN")]
    return {
        "n": len(rows), "problems_caught": tp, "problems_missed_FN": fn, "false_alarms_FP": fp,
        "correct_passes": tn, "uncertain_on_problem": unc_bad, "uncertain_on_ok": unc_ok,
        "recall_of_problems": round(tp / (tp + fn), 3) if tp + fn else None,
        "precision_of_alarms": round(tp / (tp + fp), 3) if tp + fp else None,
        "uncertain_rate": round((unc_bad + unc_ok) / len(rows), 3) if rows else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    run_dir = EVAL_DIR / "results" / args.run
    run_info = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    boxes = {b.box_id: b for b in load_manifest(run_info["split"])}

    records: dict[str, EvidenceRecord] = {}
    for path in sorted((run_dir / "records").glob("*.json")):
        if path.stem in boxes:
            records[path.stem] = EvidenceRecord.model_validate_json(path.read_text(encoding="utf-8"))
    ids = [b for b in boxes if b in records]

    # ---------------- box decision vs physical truth
    confusion = Counter()
    per_scenario = defaultdict(Counter)
    by_cause = defaultdict(Counter)
    failures = []
    for bid in ids:
        box, rec = boxes[bid], records[bid]
        truth, agent = box.decision_truth, rec.outcome.decision.value
        confusion[(truth, agent)] += 1
        s = per_scenario[box.scenario]
        s["n"] += 1
        s["correct"] += agent == truth
        s["uncertain"] += agent == "UNCERTAIN"
        s["false_seal"] += truth == "STOP_AND_FIX" and agent == "SEAL"
        s["false_stop"] += truth == "SEAL" and agent == "STOP_AND_FIX"
        if agent != truth:
            failures.append((bid, box, rec))
        # Occlusion vs everything else. "hidden" in the manifest's conditions means an item was
        # (partly) under another item or filler when photographed, noted while packing.
        g = by_cause["occlusion" if box.hidden else "other"]
        g["n"] += 1
        g["correct"] += agent == truth
        g["uncertain"] += agent == "UNCERTAIN"
        g["false_seal"] += truth == "STOP_AND_FIX" and agent == "SEAL"
        g["false_stop"] += truth == "SEAL" and agent == "STOP_AND_FIX"

    bad = sum(v for (t, _), v in confusion.items() if t == "STOP_AND_FIX")
    good = sum(v for (t, _), v in confusion.items() if t == "SEAL")
    false_seal = confusion[("STOP_AND_FIX", "SEAL")]
    false_stop = confusion[("SEAL", "STOP_AND_FIX")]
    uncertain = sum(v for (_, a), v in confusion.items() if a == "UNCERTAIN")
    pending = sum(v for (_, a), v in confusion.items() if a == "PENDING")
    decided = [(boxes[b].decision_truth, records[b].outcome.decision.value) for b in ids
               if records[b].outcome.decision.value in ("SEAL", "STOP_AND_FIX")]

    # ---------------- per check vs physical truth
    # Identity and count are scored separately: finding a SKU is much easier than counting
    # three of them when they overlap, and one blended number would hide which one fails.
    present_rows, count_rows, unexpected_rows = [], [], []
    for bid in ids:
        box, rec = boxes[bid], records[bid]
        checks = {c.check_key: c.verdict.value for c in rec.checks}
        if rec.outcome.decision.value == "PENDING":
            continue
        for sku in box.expected:
            in_box = box.actual.get(sku, 0) >= 1
            present_rows.append(("PASS" if in_box else "FAIL", checks.get(f"line_present:{sku}", "UNCERTAIN")))
            if in_box:  # a count only means something once the item is really there
                count_rows.append((box.line_truth(sku), checks.get(f"line_quantity:{sku}", "UNCERTAIN")))
        w, e = checks.get("wrong_item", "UNCERTAIN"), checks.get("extra_item", "UNCERTAIN")
        agent_unexpected = "FAIL" if "FAIL" in (w, e) else ("UNCERTAIN" if "UNCERTAIN" in (w, e) else "PASS")
        unexpected_rows.append((box.unexpected_truth, agent_unexpected))

    # ---------------- humans
    labels = load_labels()
    human = {}
    names = list(labels)[:2]
    if len(names) == 2:
        a_lab, b_lab = labels[names[0]], labels[names[1]]
        both = [b for b in ids if b in a_lab and b in b_lab]
        human["labellers"] = names
        human["all_labels_made_before_the_agent_ran"] = labelled_before(names, run_info.get("started_at"))
        human["boxes_labelled_by_both"] = len(both)
        human["kappa_human_vs_human"] = cohen_kappa([a_lab[b] for b in both], [b_lab[b] for b in both], DECISIONS)
        agree = [b for b in both if a_lab[b] == b_lab[b]]
        human["humans_agree_on"] = len(agree)
        human["kappa_agent_vs_human_consensus"] = cohen_kappa(
            [records[b].outcome.decision.value for b in agree], [a_lab[b] for b in agree], DECISIONS)
        for name in names:
            lab = labels[name]
            got = [b for b in ids if b in lab]
            human[f"{name}_vs_physical_truth"] = pct(sum(lab[b] == boxes[b].decision_truth for b in got), len(got))
            human[f"{name}_uncertain"] = pct(sum(lab[b] == "UNCERTAIN" for b in got), len(got))

    # ---------------- latency, cost, photo quality
    fresh = [r for r in records.values() if not (r.observations or {}).get("cached_response")
             and r.outcome.decision.value != "PENDING"]
    lat = sorted(c.latency_ms for r in records.values() for c in r.checks[-1:] if c.latency_ms)
    tokens = [r.observations.get("usage", {}).get("total_tokens", 0) for r in records.values() if r.observations]
    costs = [r.observations.get("cost_usd") for r in records.values()
             if r.observations and r.observations.get("cost_usd") is not None]
    gate_fail = sum(any(i.quality.gate == "FAIL" for i in r.images) for r in records.values())

    metrics = {
        "run": args.run, **run_info, "boxes_scored": len(ids),
        "box_decision": {
            "bad_boxes": bad, "good_boxes": good,
            "false_SEAL_rate": pct(false_seal, bad),
            "false_STOP_rate": pct(false_stop, good),
            "uncertain_rate": pct(uncertain, len(ids)),
            "uncertain_on_bad_boxes": pct(confusion[("STOP_AND_FIX", "UNCERTAIN")], bad),
            "uncertain_on_good_boxes": pct(confusion[("SEAL", "UNCERTAIN")], good),
            "accuracy_when_decided": pct(sum(t == a for t, a in decided), len(decided)),
            "pending_model_failures": pending,
            "pending_rate": pct(pending, len(ids)),
            "confusion": {f"{t} -> {a}": v for (t, a), v in sorted(confusion.items())},
        },
        "checks": {"all_items_present: line_present (per order line)": check_table(present_rows),
                   "quantities_correct: line_quantity (per order line whose item is in the box)": check_table(count_rows),
                   "unexpected_product: wrong_item or extra_item (per box)": check_table(unexpected_rows)},
        "per_scenario": {k: dict(v) for k, v in sorted(per_scenario.items())},
        "occlusion_vs_other": {k: dict(v) for k, v in sorted(by_cause.items())},
        "humans": human,
        "latency_ms": {"p50": lat[len(lat) // 2] if lat else None,
                       "p95": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
                       "note": "model call only, as recorded when first run (cached re-runs keep the original latency)"},
        "tokens_per_box_mean": round(statistics.mean(tokens)) if tokens else None,
        "cost_usd_per_box_mean": round(statistics.mean(costs), 5) if costs else None,
        "fresh_model_calls_this_run": len(fresh),
        "boxes_with_a_photo_failing_the_quality_gate": gate_fail,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    # ---------------- report
    bd = metrics["box_decision"]
    lines = [
        f"# Eval report: {args.run}",
        "",
        f"Split: **{run_info['split']}** · boxes scored: **{len(ids)}** · model: `{run_info['model']}`"
        f" · order revealed to model: **{run_info['reveal_order']}**"
        f" · thresholds: match {run_info['match_threshold']}, visibility {run_info['visibility_threshold']}",
        "",
        "## Box decision vs what was physically packed",
        "",
        "| Measure | Result |", "|---|---|",
        f"| **False SEAL** (wrong box would ship) | **{bd['false_SEAL_rate']}** of bad boxes |",
        f"| False STOP (good box stopped) | {bd['false_STOP_rate']} of good boxes |",
        f"| UNCERTAIN (sent to a human) | {bd['uncertain_rate']} of all boxes |",
        f"| … on bad boxes / on good boxes | {bd['uncertain_on_bad_boxes']} / {bd['uncertain_on_good_boxes']} |",
        f"| Accuracy when the agent decided | {bd['accuracy_when_decided']} |",
        f"| Model failures (\"Needs your decision\") | {bd['pending_model_failures']} boxes, {bd['pending_rate']} (target: 2% or less) |",
        "",
        "| Truth \\ Agent | SEAL | STOP_AND_FIX | UNCERTAIN | PENDING |", "|---|---|---|---|---|",
    ]
    for t in ["SEAL", "STOP_AND_FIX"]:
        lines.append(f"| {t} | " + " | ".join(str(confusion[(t, a)]) for a in ["SEAL", "STOP_AND_FIX", "UNCERTAIN", "PENDING"]) + " |")
    lines += ["", "## Per check", "",
              "FAIL means a problem is present. FN = a real problem the agent passed; FP = a false alarm.", "",
              "| Check | n | Caught | Missed (FN) | False alarm (FP) | Uncertain on problem / on OK | Recall | Precision |",
              "|---|---|---|---|---|---|---|---|"]
    for name, t in metrics["checks"].items():
        lines.append(f"| {name} | {t['n']} | {t['problems_caught']} | {t['problems_missed_FN']} | {t['false_alarms_FP']} | "
                     f"{t['uncertain_on_problem']} / {t['uncertain_on_ok']} | {t['recall_of_problems']} | {t['precision_of_alarms']} |")
    lines += ["", "## Per scenario", "", "| Scenario | n | Correct | Uncertain | False SEAL | False STOP |", "|---|---|---|---|---|---|"]
    for k, v in metrics["per_scenario"].items():
        lines.append(f"| {k} | {v['n']} | {v['correct']} | {v['uncertain']} | {v['false_seal']} | {v['false_stop']} |")
    lines += ["", "## Occlusion vs everything else", "",
              "Boxes marked `hidden` in the manifest had an item under another item or filler when photographed.",
              "One photo can't see those, so failures there are about geometry, not recognition.", "",
              "| Group | n | Correct | Uncertain | False SEAL | False STOP |", "|---|---|---|---|---|---|"]
    for k, v in metrics["occlusion_vs_other"].items():
        name = "Items hidden (occlusion)" if k == "occlusion" else "Nothing hidden (recognition, count, photo quality)"
        lines.append(f"| {name} | {v['n']} | {v['correct']} | {v['uncertain']} | {v['false_seal']} | {v['false_stop']} |")
    lines += ["", "## Human labellers (from photos only, before the agent ran)", ""]
    if human:
        lines += [f"- Labellers: {', '.join(human['labellers'])}; boxes labelled by both: {human['boxes_labelled_by_both']}",
                  f"- All labels made before the agent ran: **{human['all_labels_made_before_the_agent_ran']}**",
                  f"- Cohen's kappa, human vs human: **{human['kappa_human_vs_human']}**",
                  f"- Humans agreed on {human['humans_agree_on']} boxes; agent vs that consensus: kappa **{human['kappa_agent_vs_human_consensus']}**"]
        lines += [f"- {k.replace('_', ' ')}: {v}" for k, v in human.items() if k.endswith(("_vs_physical_truth", "_uncertain"))]
    else:
        lines.append("No label files found in eval/labels/.")
    lines += ["", "## Cost and speed", "",
              f"- Model latency p50 / p95: {metrics['latency_ms']['p50']} / {metrics['latency_ms']['p95']} ms",
              f"- Tokens per box (mean): {metrics['tokens_per_box_mean']}",
              f"- Cost per box (mean, paid-tier list price from .env): {metrics['cost_usd_per_box_mean']}",
              f"- Boxes with a photo failing the local quality gate: {gate_fail}",
              "", "## Every box the agent got wrong or sent to a human", "",
              "| Box | Scenario | Conditions | Truth | Agent | Agent's first reason |", "|---|---|---|---|---|---|"]
    for bid, box, rec in failures:
        reason = (rec.outcome.reasons or [""])[0].replace("|", "/")
        lines.append(f"| {bid} | {box.scenario} | {box.conditions} | {box.decision_truth} | {rec.outcome.decision.value} | {reason} |")
    lines += ["", "Failure-mode names and notes go in EVAL.md after reviewing these rows and their photos."]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:22]))
    print(f"\nFull report: {run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
