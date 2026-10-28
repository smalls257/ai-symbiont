"""Note-cost options: counts per tier and spell, TRAIN-fold choices, and the exploratory report."""

import json

import numpy as np
import pytest

from gate_loader import load_gate
from symbiont.eval.note_cost_options import (
    FP_HEADS,
    FP_WARN,
    NEVER,
    SPELLS,
    SPELLS_HIT,
    TP_HEADS,
    TP_WARN,
    counts,
    per_step_value,
    prepare,
    shown,
    two_tiers,
)
from symbiont.eval.note_cost_report import Arms, report
from symbiont.eval.note_cost_select import (
    FOLDS,
    PRIMARY,
    by_risk_control,
    by_value,
    catalog,
    cross_validate,
    task_folds,
)
from symbiont.eval.note_delivery import DeliveryRule, Gate, NoteTrace

content_gate = load_gate("check_results_content")
roles_gate = load_gate("check_results")


def one_session(followed, risk, boundary=None, task="t0"):
    boundary = boundary if boundary is not None else [True] * len(followed)
    return NoteTrace(task, tuple(followed), tuple(risk), tuple(boundary))


def test_a_spell_is_hit_once_however_many_notes_fall_in_it_and_tiers_split_by_risk():
    trace = one_session([True, True, False, True], [0.9, 0.6, 0.6, 0.1])
    arm = prepare([trace], ["t0"])
    row = counts(arm, shown(arm, 0.5, DeliveryRule(Gate.EVERY_STEP)), warn_at=0.8)[0]
    assert (row[TP_WARN], row[TP_HEADS], row[FP_HEADS], row[FP_WARN]) == (1, 1, 1, 0)
    assert (row[SPELLS_HIT], row[SPELLS]) == (1, 2)


def test_two_tier_settings_put_silence_first_and_never_warn_below_the_note_threshold():
    settings = two_tiers([NEVER, 0.9, 0.5])
    assert settings[0] == (NEVER, NEVER)
    assert all(high >= low for low, high in settings)
    assert len(settings) == 6


def test_choosing_by_value_stays_silent_when_no_setting_beats_zero():
    stack = np.zeros((3, 4, 8))
    stack[..., 7], stack[..., 5] = 1, 10  # sessions, steps
    stack[1, :, FP_WARN] = 5
    assert by_value(per_step_value(0.5))(stack) == (0, 0.0)


def test_risk_control_takes_the_loosest_threshold_inside_the_bound():
    stack = np.zeros((4, 50, 8))
    stack[..., 7], stack[..., 5] = 1, 10
    stack[1, :, FP_WARN] = 0.0
    stack[2, :10, FP_WARN] = 1.0  # a fifth of the tasks spend their one note on a false alarm
    stack[3, :, FP_WARN] = 1.0
    assert by_risk_control(1, 0.25)(stack)[0] == 2
    assert by_risk_control(1, 0.1)(stack)[0] == 1


def test_risk_control_never_trusts_a_loose_threshold_after_a_stricter_one_failed():
    stack = np.zeros((3, 50, 8))
    stack[..., 7], stack[..., 5] = 1, 10
    stack[1, :, FP_WARN] = 1.0  # the stricter threshold is all false alarms
    assert by_risk_control(1, 0.5)(stack)[0] == 0


def test_folds_are_balanced_and_fixed_by_the_seed():
    folds = task_folds(23, seed=7)
    assert sorted(np.bincount(folds).tolist()) == [4, 4, 5, 5, 5]
    assert np.array_equal(folds, task_folds(23, seed=7))


def test_a_held_out_fold_is_counted_with_a_setting_picked_without_it():
    stack = np.zeros((2, FOLDS, 8))
    stack[..., 7], stack[..., 5] = 1, 10
    stack[1, :, TP_WARN] = 1.0
    stack[1, 0, :2] = (0, 50)  # task 0 alone would make setting 1 a loss
    held, picked = cross_validate([stack], np.arange(FOLDS), by_value(per_step_value(0.5)))
    assert picked[0] == (0, 1)  # fold 0 picks on tasks 1-4, which like setting 1
    assert held[0, FP_WARN] == 50  # and task 0 pays for it, unseen
    assert picked[1] == (0, 0)  # every other fold sees task 0 and stays silent
    assert held[1, TP_WARN] == 0


def make_traces(seed, signal, n_tasks=25, sessions=3, steps=60):
    rng = np.random.default_rng(seed)
    traces = []
    for task in range(n_tasks):
        for _ in range(sessions):
            followed = np.zeros(steps, dtype=bool)
            for start in rng.choice(steps - 5, 3, replace=False):
                followed[start : start + 3] = True
            risk = rng.random(steps) + signal * followed
            boundary = rng.random(steps) < 0.4
            traces.append(
                NoteTrace(f"t{task:02d}", *(tuple(a.tolist()) for a in (followed, risk, boundary)))
            )
    return tuple(traces)


def build(signal=2.0, n_boot=100):
    arms = Arms(
        make_traces(1, signal),
        {s: make_traces(10 + s, signal) for s in (0, 1, 2)},
        {s: {0.1: make_traces(20 + s, 0.0), 0.3: make_traces(30 + s, signal)} for s in (0, 1, 2)},
        logistic={f: {1.0: make_traces(40 + f, signal)} for f in range(FOLDS)},
    )
    return report(arms, seed=3, n_boot=n_boot)


@pytest.fixture(scope="module")
def strong():
    return build()


def test_every_option_has_counters_beside_the_fly_over_both_floors(strong):
    for option in catalog():
        roles = {r["arm"]: r["role"] for r in strong["rows"] if r["option"] == option.key}
        assert roles["counters"] == "reference" and roles["fly"] == "under_test"
        assert roles["dense"] == "under_test" and roles["warn never"] == "floor"
        assert roles["note at every allowed step"] == "floor"
        assert roles["logistic"] == "reference"
    assert {r["split"] for r in strong["rows"]} == {"train-cv"}


def test_warn_never_earns_nothing_and_a_strong_signal_earns_notes(strong):
    rows = {(r["option"], r["arm"]): r for r in strong["rows"]}
    assert rows[(PRIMARY, "warn never")]["metrics"]["net_value_per_100_steps"]["value"] == 0.0
    assert not rows[(PRIMARY, "warn never")]["earns_notes"]
    assert rows[(PRIMARY, "fly")]["earns_notes"] and rows[("b_per_spell", "fly")]["earns_notes"]


def test_noise_earns_no_notes():
    rows = build(signal=0.0, n_boot=50)["rows"]
    learners = [r for r in rows if r["role"] != "floor" and r["option"] == "t36_per_step"]
    assert not any(r["earns_notes"] for r in learners)


def test_the_budget_caps_notes_per_session(strong):
    for row in strong["rows"]:
        if row["option"].startswith("c_budget_") and row["role"] != "floor":
            budget = int(row["option"].rsplit("_", 1)[1])
            assert row["metrics"]["notes_per_session"]["value"] <= budget


def test_the_decision_curve_names_the_costs_where_each_learner_is_useful(strong):
    curve = strong["decision_curve"]
    assert curve["costs"][0] == 0.1 and curve["costs"][-1] == 1.0
    fly = next(r for r in curve["rows"] if r["arm"] == "fly")
    assert fly["useful_costs"] and len(fly["by_cost"]) == 10


def test_the_results_hold_counts_and_labels_only(strong):
    document = json.loads(json.dumps(strong))
    assert content_gate.findings_in("note-cost.json", document) == []
    assert roles_gate.problems_in("note-cost.json", document) == []


def test_a_report_without_fly_runs_is_refused():
    with pytest.raises(ValueError, match="half a comparison"):
        report(Arms(make_traces(1, 1.0), {}, {}), seed=1)
