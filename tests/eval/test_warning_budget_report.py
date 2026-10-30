"""The exploratory budget report: counters beside every fly row, short strings only.

Violation prevented: **Paper Tiger** (a fly row without its counters row) and
**Silent Fallback** (a threshold taken from test data instead of TRAIN).
"""

import json

import numpy as np
import pytest

from symbiont.eval.warning_budget_metrics import RiskTrace
from symbiont.eval.warning_budget_report import ArmTraces, operating_point, report


def make_traces(seed, n_tasks, steps=60, signal=1.0):
    rng = np.random.default_rng(seed)
    traces = []
    for task in range(n_tasks):
        followed = rng.random(steps) < 0.15
        risk = rng.random(steps) + signal * followed
        traces.append(RiskTrace(f"t{task}", tuple(followed.tolist()), tuple(risk.tolist())))
    return tuple(traces)


def arm(seed, signal=1.0, n_train=20, n_test=12):
    return ArmTraces(
        make_traces(seed, n_train, signal=signal), make_traces(seed + 100, n_test, signal=signal)
    )


def test_the_threshold_comes_from_train_and_is_applied_unchanged_to_test():
    point = operating_point(arm(1), 0.15, [f"t{i}" for i in range(12)])
    assert point.train_flag_rate == pytest.approx(0.15, abs=0.001)
    train_only = ArmTraces(arm(1).train, make_traces(999, 12, signal=5.0))
    other = operating_point(train_only, 0.15, [f"t{i}" for i in range(12)])
    assert other.threshold == point.threshold, "test risks must not move the threshold"


def test_report_puts_counters_beside_every_fly_row_and_a_floor_under_both():
    flies = {0: arm(2), 1: arm(3), 2: arm(4)}
    result = report(arm(5, signal=0.2), flies, seed=1, n_boot=200)
    arms = {(r["arm"], r["budget"]) for r in result["rows"]}
    for budget in (0.10, 0.15, 0.20):
        assert ("counters", budget) in arms and ("fly", budget) in arms
        assert all((f"fly seed {s}", budget) in arms for s in flies)
    roles = {r["arm"]: r["role"] for r in result["rows"]}
    assert roles["counters"] == "reference" and roles["fly"] == "under_test"
    assert roles["warn on every step"] == "floor"
    assert {r["split"] for r in result["rows"]} == {"test"}


def test_the_floor_precision_is_the_base_rate_and_its_recall_is_one():
    result = report(arm(5), {0: arm(2)}, seed=1, n_boot=100)
    floor = next(r for r in result["rows"] if r["arm"] == "warn on every step")
    assert floor["metrics"]["recall"]["value"] == 1.0
    assert floor["metrics"]["flag_rate"]["value"] == 1.0
    assert 0.05 < floor["metrics"]["precision"]["value"] < 0.3


def test_a_better_risk_score_has_higher_precision_at_the_same_budget():
    strong = report(arm(6, signal=2.0), {0: arm(7, signal=0.0)}, seed=1, n_boot=200)
    by_arm = {(r["arm"], r["budget"]): r for r in strong["rows"]}
    assert (
        by_arm["counters", 0.15]["metrics"]["precision"]["value"]
        > by_arm["fly seed 0", 0.15]["metrics"]["precision"]["value"]
    )
    difference = next(d for d in strong["differences"] if d["budget"] == 0.15)
    assert difference["metrics"]["precision"]["value"] < 0


def test_the_report_is_json_with_only_short_strings():
    result = report(arm(8), {0: arm(9), 1: arm(10)}, seed=1, n_boot=100)
    text = json.dumps(result)
    strings = [v for v in _strings(result)]
    assert max(len(s) for s in strings) <= 160, max(strings, key=len)
    assert result["table_rows"] and all(isinstance(s, str) for s in result["table_rows"])
    assert json.loads(text) == result


def test_report_needs_at_least_one_fly_run():
    with pytest.raises(ValueError):
        report(arm(1), {}, seed=1, n_boot=10)


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
