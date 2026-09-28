"""Replay the organisers' pack_sample.csv through the decision engine.

`observed_in_box` is treated as perfect perception, so this measures the rule layer alone:
does it catch every box whose contents differ from the order, including the ones the
human operator sealed by mistake?
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .decision import decide
from .models import Catalogue, Decision, Order, QualityReport, parse_lines
from .vision.oracle import OraclePerceiver

PERFECT_PHOTO = QualityReport(
    gate="PASS", width=1600, height=1200, blur_var=500.0, mean_luma=128.0, clipped_pct=0.0, dark_pct=0.0
)


@dataclass
class ReplayRow:
    record_id: str
    order_id: str
    organization_id: str
    ordered: str
    observed: str
    operator_verdict: str
    agent_decision: Decision
    fix_instructions: list[str]

    @property
    def truth(self) -> str:
        return "seal" if self.ordered_counts == self.observed_counts else "stop_and_fix"

    @property
    def ordered_counts(self) -> dict[str, int]:
        return Order(order_id="x", organization_id="x", lines=parse_lines(self.ordered)).expected()

    @property
    def observed_counts(self) -> dict[str, int]:
        return Order(order_id="x", organization_id="x", lines=parse_lines(self.observed)).expected()


def replay(csv_path: str | Path, catalogue: Catalogue, settings: Settings) -> list[ReplayRow]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            order = Order(
                order_id=r["order_id"], organization_id=r["org_id"], unit_id=r["unit_id"],
                channel=r["channel"], lines=parse_lines(r["order_lines"]),
            )
            observed = Order(order_id="obs", organization_id="obs", lines=parse_lines(r["observed_in_box"])).expected()
            perception = OraclePerceiver(observed).perceive([], [], [], None)
            result = decide(order, catalogue, perception, [PERFECT_PHOTO], settings)
            rows.append(ReplayRow(
                record_id=r["record_id"], order_id=r["order_id"], organization_id=r["org_id"],
                ordered=r["order_lines"], observed=r["observed_in_box"], operator_verdict=r["operator_verdict"],
                agent_decision=result.decision, fix_instructions=result.fix_instructions,
            ))
    return rows
