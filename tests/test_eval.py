"""The eval's own arithmetic: confidence intervals, the targets table and the freeze check."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from freeze import differences  # noqa: E402
from metrics import against_targets, wilson  # noqa: E402


def test_wilson_interval_matches_known_values():
    lo, hi = wilson(0, 20)
    assert lo == 0 and round(hi, 3) == 0.161
    lo, hi = wilson(5, 50)
    assert round(lo, 3) == 0.043 and round(hi, 3) == 0.214
    assert wilson(0, 0) is None


def test_targets_report_kill_only_when_its_condition_holds():
    ok = {"false_SEAL": (0, 25), "false_STOP": (1, 25), "UNCERTAIN": (5, 50), "PENDING": (0, 50)}
    rows, kills = against_targets(ok)
    assert kills == []
    assert rows[0]["status"].startswith("met, not proven")  # 0/25 still has an upper bound of 13%

    # False SEAL above 5% trips the kill only while UNCERTAIN is 25% or lower.
    rows, kills = against_targets({**ok, "false_SEAL": (3, 25)})
    assert rows[0]["status"] == "KILL" and len(kills) == 1
    rows, kills = against_targets({**ok, "false_SEAL": (3, 25), "UNCERTAIN": (15, 50)})
    assert rows[0]["status"] == "missed" and not any("False SEAL" in k for k in kills)

    rows, kills = against_targets({**ok, "PENDING": (4, 50)})
    assert rows[3]["status"] == "KILL"


def test_freeze_names_what_changed():
    frozen = {"config": {"model": "m1", "prompt_version": "pack-v2"}, "manifest_rows_sha256": "a",
              "labels_sha256": {"ana.csv": "x", "ben.csv": "y"}}
    now = {"config": {"model": "m2", "prompt_version": "pack-v2"}, "manifest_rows_sha256": "a",
           "labels_sha256": {"ana.csv": "x", "ben.csv": "z"}}
    assert differences(frozen, now) == ["config: model", "labels_sha256: ben.csv"]
    assert differences(now, now) == []
