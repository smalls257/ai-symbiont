"""Net benefit, the train-chosen threshold and the live-warner rule, on synthetic numbers."""

import numpy as np
import pytest

from symbiont.eval.net_benefit import (
    NEVER,
    Standing,
    Warner,
    best_threshold,
    live_warner,
    net_benefit,
    net_benefit_gap,
    net_benefit_interval,
    standing,
)


def test_net_benefit_is_true_warnings_minus_cost_times_false_over_steps():
    totals = np.array([[10.0, 30.0, 10.0, 50.0]])  # tp fp fn tn over 100 steps
    assert net_benefit(totals, 0.5)[0] == pytest.approx(-0.05)
    assert net_benefit(totals, 0.25)[0] == pytest.approx(0.025)


def test_break_even_precision_at_half_cost_is_one_third():
    totals = np.array([[10.0, 20.0, 0.0, 70.0]])  # precision 1/3
    assert net_benefit(totals, 0.5)[0] == pytest.approx(0.0)


def test_threshold_is_the_train_maximizer_and_ties_go_to_the_higher_one():
    risks = [5.0, 5.0, 4.0, 3.0, 3.0, 1.0]
    followed = [True, True, False, True, True, False]
    choice = best_threshold(risks, followed, 0.5)
    # at 5: tp2 -> 2; at 4: 2-0.5=1.5; at 3: 4-0.5=3.5; at 1: 4-1=3
    assert choice.threshold == 3.0
    assert choice.net_benefit == pytest.approx(3.5 / 6)
    tie = best_threshold([2.0, 1.0], [True, True], 0.5)
    assert tie.threshold == 1.0  # 1 and 2 true warnings at 2 vs 1: lower risk adds a true one
    flat = best_threshold([2.0, 1.0, 0.5], [True, False, False], 1.0)
    assert flat.threshold == 2.0


def test_a_learner_that_cannot_beat_never_warning_gets_no_threshold():
    choice = best_threshold([3.0, 2.0, 1.0], [False, False, True], 0.5)
    assert choice.threshold == NEVER and choice.net_benefit == 0.0


def test_a_missing_risk_or_no_steps_raises_instead_of_defaulting():
    with pytest.raises(ValueError, match="no risk score"):
        best_threshold([1.0, None], [True, False], 0.5)
    with pytest.raises(ValueError, match="zero train steps"):
        best_threshold([], [], 0.5)


def test_a_higher_false_alarm_cost_never_lowers_the_threshold():
    rng = np.random.default_rng(3)
    risks = rng.random(500)
    followed = (risks + rng.normal(0, 0.4, 500)) > 0.8
    thresholds = [
        best_threshold(list(risks), list(followed), c).threshold for c in (0.25, 0.5, 1.0)
    ]
    assert thresholds == sorted(thresholds)


def test_interval_and_gap_use_the_same_task_draws():
    counts = np.array([[3.0, 1.0, 1.0, 15.0], [0.0, 2.0, 2.0, 16.0], [4.0, 0.0, 0.0, 16.0]])
    draws = np.random.default_rng(0).multinomial(3, [1 / 3] * 3, size=300)
    one = net_benefit_interval(counts, draws, 0.5)
    assert one["ci95_low"] <= one["value"] <= one["ci95_high"]
    same = net_benefit_gap(counts, counts, draws, 0.5)
    assert same["value"] == 0.0 and same["ci95_low"] == same["ci95_high"] == 0.0
    assert standing(same) is Standing.TIE


def ci(value, low, high):
    return {"value": value, "ci95_low": low, "ci95_high": high}


def verdict(counters, dense, fly, dense_gap, fly_gap):
    benefit = {Warner.COUNTERS: counters, Warner.DENSE: dense, Warner.FLY: fly}
    return live_warner(benefit, {Warner.DENSE: dense_gap, Warner.FLY: fly_gap})


NOTHING = ci(-0.01, -0.02, 0.0)
TIED = ci(0.0, -0.01, 0.01)
CLEAR = ci(0.01, 0.005, 0.02)


def test_nobody_beating_never_warning_means_recall_only():
    assert verdict(NOTHING, NOTHING, ci(0.001, 0.0, 0.01), TIED, TIED) is Warner.NONE


def test_the_best_candidate_goes_live_only_if_it_clearly_beats_counters():
    good = ci(0.02, 0.01, 0.03)
    better = ci(0.03, 0.02, 0.04)
    assert verdict(good, NOTHING, better, TIED, TIED) is Warner.COUNTERS
    assert verdict(good, NOTHING, better, TIED, CLEAR) is Warner.FLY


def test_a_winner_other_than_counters_goes_live_when_counters_do_not_beat_nothing():
    assert verdict(NOTHING, ci(0.02, 0.01, 0.03), NOTHING, TIED, TIED) is Warner.DENSE


def test_equal_points_go_to_the_simplest_learner():
    same = ci(0.02, 0.01, 0.03)
    assert verdict(same, same, same, TIED, TIED) is Warner.COUNTERS
    assert verdict(NOTHING, same, same, CLEAR, CLEAR) is Warner.DENSE
