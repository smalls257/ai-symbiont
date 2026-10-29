"""The probe table: percentiles, per-move token means, and no price for an unpriced arm."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts" / "act1"))
report = importlib.import_module("spark_report")


def game(ended="exited", pains=2, died=False, seconds=(1.0, 2.0, 3.0)):
    return {"ended": ended, "pains": pains, "progress": 0.5, "kills": 1, "died": died,
            "seconds": list(seconds)}  # fmt: skip


def call(cost=0.001):
    return {"prompt": 400, "cached": 100, "completion": 50, "reasoning": 30, "cost_usd": cost}


def test_nearest_rank_percentile():
    values = [float(n) for n in range(1, 11)]
    assert report.percentile(values, 0.5) in (5.0, 6.0) and report.percentile(values, 0.9) == 9.0


def test_an_arm_row_counts_exits_deaths_and_prices_from_the_ledger():
    row = report.arm_summary([game(), game("decision_cap", died=True)], [call(), call()])
    assert (row["games"], row["exits"], row["died"], row["calls"]) == (2, 1, 1, 2)
    assert row["cost_usd"] == pytest.approx(0.002)
    assert row["tokens_per_move"] == {
        "prompt": 400,
        "cached": 100,
        "completion": 50,
        "reasoning": 30,
    }
    assert row["sec_median"] == 2.0


def test_an_arm_with_no_ledger_rows_raises_instead_of_costing_nothing():
    with pytest.raises(ValueError, match="no ledger rows"):
        report.arm_summary([game()], [])
