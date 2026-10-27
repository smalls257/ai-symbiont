"""Budgeted operating point and the live warning budget.

Violation prevented: **Paper Tiger** (a learner that warns on two steps in
three looks accurate and is unusable) and **Silent Fallback** (a false alarm
that nobody tells the learner about teaches it nothing).
"""

import numpy as np
import pytest

from record_builders import run, session
from symbiont.core.mushroom import Mushroom
from symbiont.core.slot import Outcome, Situation
from symbiont.core.warning_budget import (
    Admission,
    BudgetState,
    WarningBudget,
    calibrate_budget,
    flagged_at,
)
from symbiont.miner.painpoint import PainPoint, Signal, Signature

FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_a.py", "ImportError"))
OTHER = Signature(Signal.REWORKED_EDIT, ("a.py",))
X = np.zeros(86, dtype=np.float32)


def test_threshold_flags_the_requested_share_of_a_continuous_stream():
    risks = list(np.random.default_rng(0).random(2000))
    for budget in (0.10, 0.15, 0.20):
        threshold = calibrate_budget(risks, budget)
        share = sum(flagged_at(risks, threshold)) / len(risks)
        assert share == pytest.approx(budget, abs=1 / len(risks))


def test_tied_risks_cannot_hit_the_budget_so_the_closest_share_wins():
    # 85% of steps at 0, 8% at 1, 5% at 2, 2% at 3: a 10% budget lands on 8% (>=1 is 15%, >=2 is 7%)
    risks = [0.0] * 85 + [1.0] * 8 + [2.0] * 5 + [3.0] * 2
    assert calibrate_budget(risks, 0.10) == 2.0  # 7% is closer to 10% than 15% is
    assert calibrate_budget(risks, 0.15) == 1.0  # exactly 15%


def test_a_tie_between_two_shares_goes_to_the_stricter_threshold():
    risks = (
        [0.0] * 80 + [1.0] * 10 + [2.0] * 10
    )  # >=2 is 10%, >=1 is 20%: budget 0.15 is equidistant
    assert calibrate_budget(risks, 0.15) == 2.0


def test_budget_outside_zero_one_or_no_steps_raises():
    for bad in (0.0, 1.0, -0.1):
        with pytest.raises(ValueError):
            calibrate_budget([1.0, 2.0], bad)
    with pytest.raises(ValueError):
        calibrate_budget([], 0.1)


def test_a_missing_risk_raises_rather_than_counting_as_quiet():
    with pytest.raises(ValueError):
        calibrate_budget([1.0, None, 2.0], 0.5)
    with pytest.raises(ValueError):
        flagged_at([1.0, None], 0.5)


def test_default_budget_is_three_warnings_per_twenty_steps():
    assert WarningBudget() == WarningBudget.for_budget(0.15, per_steps=20)
    assert WarningBudget().max_warnings == 3


def test_cap_blocks_the_warning_over_the_limit_and_frees_up_after_the_window():
    policy = WarningBudget(max_warnings=2, per_steps=10, repeat_window=0)
    state = BudgetState()
    seen = []
    for step in (1, 2, 3, 4):
        verdict, state = policy.admit(state, step, FAILED, X)
        seen.append(verdict)
    assert seen == [Admission.ALLOWED, Admission.ALLOWED, Admission.CAPPED, Admission.CAPPED]
    verdict, state = policy.admit(state, 11, FAILED, X)  # step 1 has left the window
    assert verdict is Admission.ALLOWED


def test_the_same_signature_inside_the_window_is_a_repeat_but_another_is_not():
    policy = WarningBudget(max_warnings=10, per_steps=20, repeat_window=5)
    _, state = policy.admit(BudgetState(), 1, FAILED, X)
    verdict, state = policy.admit(state, 4, FAILED, X)
    assert verdict is Admission.REPEAT
    verdict, state = policy.admit(state, 4, OTHER, X)
    assert verdict is Admission.ALLOWED
    verdict, state = policy.admit(state, 7, FAILED, X)  # more than 5 steps after the first
    assert verdict is Admission.ALLOWED


def test_a_suppressed_repeat_does_not_use_up_the_cap():
    policy = WarningBudget(max_warnings=2, per_steps=20, repeat_window=5)
    _, state = policy.admit(BudgetState(), 1, FAILED, X)
    for step in (2, 3, 4):
        verdict, state = policy.admit(state, step, FAILED, X)
        assert verdict is Admission.REPEAT
    verdict, _ = policy.admit(state, 5, OTHER, X)
    assert verdict is Admission.ALLOWED


def test_admit_leaves_the_old_state_untouched():
    policy = WarningBudget()
    before = BudgetState()
    policy.admit(before, 1, FAILED, X)
    assert before == BudgetState()


def test_a_warning_followed_by_its_signature_settles_as_trouble_followed():
    policy = WarningBudget()
    _, state = policy.admit(BudgetState(), 3, FAILED, X)
    state, settled = policy.settle(state, 5, frozenset({FAILED}))
    assert [s.outcome for s in settled] == [Outcome(True, FAILED)]
    assert state.unsettled == ()


def test_a_warning_not_followed_within_five_steps_is_a_false_alarm():
    policy = WarningBudget()
    _, state = policy.admit(BudgetState(), 3, FAILED, X)
    state, settled = policy.settle(state, 7, frozenset({OTHER}))
    assert settled == () and len(state.unsettled) == 1  # four steps on: still open
    state, settled = policy.settle(state, 8, frozenset())
    assert [s.outcome.pain_point_followed for s in settled] == [False]
    assert state.unsettled == ()


def test_trouble_on_the_fifth_step_still_counts_as_followed():
    policy = WarningBudget()
    _, state = policy.admit(BudgetState(), 3, FAILED, X)
    _, settled = policy.settle(state, 8, frozenset({FAILED}))
    assert settled[0].outcome.pain_point_followed is True


def test_trouble_on_the_warning_step_itself_is_not_a_follow_up():
    policy = WarningBudget()
    _, state = policy.admit(BudgetState(), 3, FAILED, X)
    state, settled = policy.settle(state, 3, frozenset({FAILED}))
    assert settled == () and len(state.unsettled) == 1


def test_a_late_settle_does_not_count_trouble_outside_the_window():
    """settle need not be called every step: trouble seen at step 20 is not a
    follow-up to a warning at step 3, so it is a false alarm."""
    policy = WarningBudget()
    _, state = policy.admit(BudgetState(), 3, FAILED, X)
    state, settled = policy.settle(state, 20, frozenset({FAILED}))
    assert [s.outcome.pain_point_followed for s in settled] == [False]
    assert state.unsettled == ()


def test_false_alarm_fed_back_lowers_the_fly_risk_for_that_pattern():
    """Direction of the learn rule: a punished pattern has depressed weights
    (risk up); a calm outcome relaxes them (risk down). A false alarm is a
    calm outcome for the pattern that warned."""
    fly = Mushroom(seed=0)
    x = np.random.default_rng(1).random(86).astype(np.float32)
    other = np.random.default_rng(2).random(86).astype(np.float32)
    state = fly.initial_state(0)
    for _ in range(3):
        state = fly.learn(x, Outcome(True, FAILED), state)
    prefix = tuple(session(run("pytest a.py")))
    context = Situation("p", prefix, (PainPoint(FAILED, "s0", 0, ()),), ())
    risk_before = _risk(fly, x, state, context)

    policy = WarningBudget()
    _, budget_state = policy.admit(BudgetState(), 1, FAILED, x)
    _, settled = policy.settle(budget_state, 6, frozenset())
    for item in settled:
        state = fly.learn(item.x, item.outcome, state)

    assert _risk(fly, x, state, context) < risk_before
    assert _risk(fly, other, state, context) == pytest.approx(
        _risk(fly, other, fly.initial_state(0), context), abs=0.02
    )


def _risk(fly, x, state, context):
    risk = fly.decide(x, context, state).risk
    assert risk is not None
    return risk
