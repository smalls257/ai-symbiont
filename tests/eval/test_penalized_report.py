"""The penalized report: choices from TRAIN, counters beside the fly, a rule-made verdict."""

import json

import numpy as np
import pytest

from symbiont.eval.penalized_report import pick_dense, report, train_choice
from symbiont.eval.warning_budget_metrics import RiskTrace
from symbiont.eval.warning_budget_report import ArmTraces


def make_traces(seed, n_tasks, signal, steps=60):
    rng = np.random.default_rng(seed)
    traces = []
    for task in range(n_tasks):
        followed = rng.random(steps) < 0.15
        risk = rng.random(steps) + signal * followed
        traces.append(RiskTrace(f"t{task}", tuple(followed.tolist()), tuple(risk.tolist())))
    return tuple(traces)


def arm(seed, signal, n_train=20, n_test=12):
    return ArmTraces(make_traces(seed, n_train, signal), make_traces(seed + 100, n_test, signal))


def build(signal=3.0, n_boot=200):
    flies = {s: arm(s, signal) for s in (0, 1, 2)}
    dense = {s: {0.1: arm(10 + s, 0.0), 0.3: arm(20 + s, signal)} for s in (0, 1, 2)}
    return report(arm(5, signal), flies, dense, seed=1, n_boot=n_boot)


def test_counters_sit_beside_every_fly_row_at_every_cost_and_roles_are_labeled():
    result = build()
    roles = {(r["arm"], r["cost"]): r["role"] for r in result["rows"]}
    for cost in (0.5, 0.25, 1.0):
        assert roles[("counters", cost)] == "reference"
        assert roles[("fly", cost)] == "under_test" and roles[("dense", cost)] == "under_test"
        assert roles[("warn never", cost)] == "floor"
        assert roles[("warn on every step", cost)] == "floor"
    assert {r["split"] for r in result["rows"]} == {"test"}


def test_warn_never_earns_exactly_zero():
    row = next(r for r in build()["rows"] if r["arm"] == "warn never" and r["cost"] == 0.5)
    assert row["metrics"]["net_benefit_per_step"]["value"] == 0.0
    assert row["metrics"]["net_benefit_per_step"]["ci95_low"] == 0.0


def test_a_strong_signal_beats_never_warning_and_the_verdict_names_a_learner():
    verdict = build(signal=3.0)["verdict"]
    assert verdict["live_warner"] in {"counters", "dense", "fly"}


def test_pure_noise_means_recall_only():
    noisy = build(signal=0.0, n_boot=300)
    assert noisy["verdict"]["live_warner"] == "none"
    for settings in noisy["chosen_on_train"]["0.5"].values():
        assert settings["warns_never"] or settings["train_net_benefit_per_step"] > 0


def test_thresholds_and_rates_come_from_train_not_test():
    base = arm(1, 3.0)
    altered = ArmTraces(base.train, make_traces(999, 12, 9.0))
    assert train_choice(base, 0.5) == train_choice(altered, 0.5)
    by_rate = {0.1: arm(2, 0.0), 0.3: arm(3, 3.0)}
    swapped_test = {r: ArmTraces(a.train, make_traces(7, 12, 0.0)) for r, a in by_rate.items()}
    tasks = [f"t{i}" for i in range(12)]
    assert pick_dense(by_rate, 0.5, tasks).learning_rate == 0.3
    assert pick_dense(swapped_test, 0.5, tasks).learning_rate == 0.3


def test_the_result_is_json_and_holds_no_infinity():
    text = json.dumps(build(), allow_nan=False)
    assert "Infinity" not in text


def test_a_report_without_a_fly_or_dense_run_refuses():
    with pytest.raises(ValueError, match="counters row"):
        report(arm(5, 1.0), {}, {}, seed=1, n_boot=50)
