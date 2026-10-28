"""Scored T48 rules: fixed-threshold counts, verdict over five rows, standing, confirm call."""

import numpy as np
import pytest

from symbiont.eval.confirm_report import (
    CLASSIFIER,
    COUNTERS,
    DENSE,
    FLY,
    FLY_FIXED,
    TIE_ORDER,
    confirm_call,
    fixed_counts,
    layout_of,
    standing,
    thresholds_of,
    verdict,
)
from symbiont.eval.note_cost_options import NEVER, count_stack, prepare
from symbiont.eval.note_cost_scored import test_counts as t46_test_counts
from symbiont.eval.note_cost_scored_report import PRIMARY, registered_options
from symbiont.eval.note_delivery import NoteTrace


def ci(value, low, high=1.0):
    return {"value": value, "ci95_low": low, "ci95_high": high}


def benefits(**over):
    base = {name: ci(0.0, -0.1) for name in TIE_ORDER}
    base.update(over)
    return base


def traces(seed, tasks=("t1", "t2", "t3")):
    rng = np.random.default_rng(seed)
    found = []
    for task in tasks:
        for _ in range(2):
            n = 30
            followed = tuple(bool(x) for x in rng.random(n) < 0.2)
            risks = tuple(float(x) for x in rng.random(n))
            boundary = tuple(bool(x) for x in rng.random(n) < 0.3)
            found.append(NoteTrace(task, followed, risks, boundary))
    return tuple(found)


def primary():
    return next(o for o in registered_options() if o.key == PRIMARY)


def test_fixed_counts_match_the_t46_scorer_at_the_same_setting():
    option, train, test = primary(), traces(0), traces(1)
    stack = count_stack(prepare(train, ["t1", "t2", "t3"]), option.rule, option.tiers)
    setting, _ = option.choose(stack.counts)
    expected = t46_test_counts(prepare(test, ["t1", "t2", "t3"]), stack, setting, option)
    found = fixed_counts(test, ["t1", "t2", "t3"], stack.settings[setting], option)
    assert np.array_equal(found, expected)


def test_nobody_earns_means_none():
    assert verdict(benefits(), {}) == "none"


def test_the_best_earner_must_clear_counters():
    earn = benefits(**{FLY_FIXED: ci(0.2, 0.05), COUNTERS: ci(0.1, 0.01)})
    assert verdict(earn, {FLY_FIXED: ci(0.1, -0.01)}) == COUNTERS
    assert verdict(earn, {FLY_FIXED: ci(0.1, 0.01)}) == FLY_FIXED


def test_ties_go_to_the_plainest_row():
    earn = benefits(**{CLASSIFIER: ci(0.2, 0.05), DENSE: ci(0.2, 0.05), FLY: ci(0.2, 0.05)})
    gaps = {name: ci(0.1, 0.01) for name in (CLASSIFIER, DENSE, FLY)}
    assert verdict(earn, gaps) == CLASSIFIER


def test_standing_words():
    assert standing(ci(0.1, 0.01, 0.2)) == "better"
    assert standing(ci(0.0, -0.01, 0.2)) == "tie"
    assert standing(ci(-0.1, -0.2, -0.01)) == "worse"


def diffs(fly_counters_low, fly_classifier_low):
    return {
        f"{FLY_FIXED} minus {COUNTERS}": ci(0.1, fly_counters_low),
        f"{FLY_FIXED} minus {CLASSIFIER}": ci(0.0, fly_classifier_low),
    }


def test_confirm_needs_the_classifier_live_and_the_fly_between():
    earn = benefits(**{CLASSIFIER: ci(0.2, 0.05)})
    assert confirm_call(CLASSIFIER, earn, diffs(0.01, -0.05)) == "confirms"
    assert confirm_call(COUNTERS, earn, diffs(0.01, -0.05)) == "contradicts"
    assert confirm_call(CLASSIFIER, earn, diffs(-0.01, -0.05)) == "contradicts"
    assert confirm_call(CLASSIFIER, earn, diffs(0.01, 0.01)) == "contradicts"
    assert confirm_call(CLASSIFIER, benefits(), diffs(0.01, -0.05)) == "contradicts"


def test_layout_pools_repositories_in_sorted_order():
    lay = layout_of({"b": traces(0, ("x",)), "a": traces(1, ("y", "z"))}, seed=1, n_boot=20)
    assert lay.repos == ("a", "b") and list(lay.members("b")) == [2]
    assert np.all(lay.draws[:, :2].sum(axis=1) == 2)


def test_a_silent_tier_reads_as_never():
    assert thresholds_of({"note_at_or_above": 0.5, "warning_at_or_above": None}) == (0.5, NEVER)
    with pytest.raises(KeyError):
        thresholds_of({})
