"""The meta-learnable filler contract, for the fly and the from-scratch net.

Violation prevented: **Leaky Narrative** (a trainer that must know each
filler's internals) and **Paper Tiger** (a second filler that passes its shape
tests but learns nothing, or a cost that never changes behavior).
"""

import numpy as np
import pytest

from record_builders import run, session
from symbiont.core.counters import Counters
from symbiont.core.dense import N_HIDDEN, DenseNet
from symbiont.core.meta import (
    Calibrator,
    MetaLearnable,
    MetaStart,
    NotMetaLearnableError,
    query_loss,
    require_meta_learnable,
)
from symbiont.core.mushroom import N_KC, Mushroom
from symbiont.core.slot import Outcome, Situation, event_fields
from symbiont.core.warning_budget import (
    BudgetState,
    WarningBudget,
    warn_probability_threshold,
)
from symbiont.miner.painpoint import PainPoint, Signal, Signature

FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "a.py", "ImportError"))
FILLERS = [Mushroom(seed=1), DenseNet(seed=1)]
IDS = ["mushroom", "dense"]


def pattern(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).random(86).astype(np.float32)


def followed(cost: float = 1.0) -> Outcome:
    return Outcome(True, FAILED, false_alarm_cost=cost)


def calm(cost: float = 1.0) -> Outcome:
    return Outcome(False, FAILED, false_alarm_cost=cost)


def a_start(filler) -> MetaStart:
    base = filler.meta_start(filler.initial_state(0))
    jitter = np.random.default_rng(7).normal(0, 0.05, len(base.readout))
    return MetaStart(base.readout + jitter, Calibrator(2.0, -0.5))


@pytest.mark.parametrize("filler", FILLERS, ids=IDS)
def test_filler_satisfies_the_contract(filler):
    assert isinstance(filler, MetaLearnable)
    assert require_meta_learnable(filler) is filler


def test_counters_are_refused_by_name():
    with pytest.raises(NotMetaLearnableError, match="counters"):
        require_meta_learnable(Counters())


@pytest.mark.parametrize("filler", FILLERS, ids=IDS)
def test_fresh_state_reproduces_the_start(filler):
    start = a_start(filler)
    again = filler.meta_start(filler.fresh_state(start))
    assert np.array_equal(again.readout, start.readout)
    assert again.calibrator == start.calibrator
    assert filler.fresh_state(start).w_out is not start.readout


@pytest.mark.parametrize("filler", FILLERS, ids=IDS)
def test_inner_step_is_pure_and_deterministic(filler):
    start, x = a_start(filler), pattern(3)
    before = start.as_vector().copy()
    first = filler.inner_step(start, x, followed())
    assert np.array_equal(start.as_vector(), before)
    second = filler.inner_step(start, x, followed())
    assert np.array_equal(first.as_vector(), second.as_vector())
    twin = type(filler)(seed=1).inner_step(start, x, followed())
    assert np.array_equal(first.as_vector(), twin.as_vector())
    other_seed = type(filler)(seed=2).inner_step(start, x, followed())
    assert not np.array_equal(first.as_vector(), other_seed.as_vector())


@pytest.mark.parametrize("filler", FILLERS, ids=IDS)
def test_inner_step_moves_the_start_toward_the_outcome(filler):
    start, x = a_start(filler), pattern(3)
    after = filler.inner_step(start, x, followed())
    assert filler.query_gradient(start, x, followed()).readout.shape == start.readout.shape
    prob = lambda s: s.calibrator.probability(  # noqa: E731
        filler.readout_view(x, filler.fresh_state(s)).raw(s.readout)
    )
    assert prob(after) > prob(start)


@pytest.mark.parametrize("filler", FILLERS, ids=IDS)
@pytest.mark.parametrize("outcome", [followed(), calm(3.0)], ids=["miss", "false-alarm"])
def test_query_gradient_matches_finite_differences(filler, outcome):
    start, x = a_start(filler), pattern(5)
    view = filler.readout_view(x, filler.fresh_state(start))
    grad = filler.query_gradient(start, x, outcome).as_vector()
    vector = start.as_vector()
    cells = [0, 5, len(vector) - 2, len(vector) - 1]
    for i in cells:
        step = np.zeros_like(vector)
        step[i] = 1e-6
        up = query_loss(start.with_vector(vector + step), view, outcome)
        down = query_loss(start.with_vector(vector - step), view, outcome)
        assert grad[i] == pytest.approx((up - down) / 2e-6, abs=1e-6)


def test_reptile_move_and_vector_round_trip():
    a = MetaStart(np.zeros(3), Calibrator(1.0, 0.0))
    b = MetaStart(np.ones(3), Calibrator(3.0, 2.0))
    half = a.toward(b, 0.5)
    assert np.allclose(half.readout, 0.5) and half.calibrator == Calibrator(2.0, 1.0)
    with pytest.raises(ValueError, match="expected a vector"):
        a.with_vector(np.zeros(3))


def test_sizes_are_the_stated_constants():
    assert DenseNet(seed=0).initial_state(0).w_out.shape == (N_HIDDEN,)
    assert Mushroom(seed=0).initial_state(0).w_out.shape == (N_KC,)


def test_dense_learns_a_separable_task_within_ten_outcomes():
    net = DenseNet(seed=0)
    state = net.initial_state(0)
    trouble, fine = pattern(11), pattern(12)
    for _ in range(5):
        state = net.learn(trouble, followed(), state)
        state = net.learn(fine, calm(), state)
    assert net.trouble_probability(trouble, state) > 0.5 > net.trouble_probability(fine, state)
    unseen = pattern(11) + np.random.default_rng(0).normal(0, 0.02, 86).astype(np.float32)
    assert net.trouble_probability(unseen, state) > 0.5


def test_dense_flags_the_kind_of_trouble_it_learned():
    net, x = DenseNet(seed=0), pattern(11)
    state = net.initial_state(0)
    for _ in range(3):
        state = net.learn(x, followed(), state)
    point = PainPoint(FAILED, "s0", 0, (("s0", 0),))
    sit = Situation("p", tuple(session(run("pytest a.py"))), (point,), ())
    decision = net.decide(x, sit, state)
    assert decision.trouble == FAILED
    assert "risk" not in event_fields(decision) and "risk" not in repr(decision)
    quiet = net.decide(pattern(12), sit, net.learn(pattern(12), calm(), net.initial_state(0)))
    assert quiet.trouble is None and quiet.reason_none


def _after_noisy_stream(filler, cost: float, x: np.ndarray, rate: float = 0.6):
    state = filler.initial_state(0)
    for trouble in np.random.default_rng(0).random(200) < rate:
        outcome = followed(cost) if trouble else calm(cost)
        state = filler.learn(x, outcome, state)
    return filler.trouble_probability(x, state)


@pytest.mark.parametrize("make", [lambda: Mushroom(seed=1), lambda: DenseNet(seed=1)], ids=IDS)
def test_false_alarm_cost_lowers_risk_on_an_ambiguous_pattern(make):
    x = pattern(21)
    balanced = _after_noisy_stream(make(), 1.0, x)
    costly = _after_noisy_stream(make(), 4.0, x)
    assert costly < balanced


def test_dense_stops_warning_on_a_pattern_that_is_mostly_a_false_alarm():
    net, x = DenseNet(seed=1), pattern(21)
    assert _after_noisy_stream(net, 1.0, x) > 0.5 >= _after_noisy_stream(net, 4.0, x)


def test_the_bayes_threshold_rises_with_the_cost():
    assert warn_probability_threshold(1.0) == 0.5
    assert warn_probability_threshold(4.0) == pytest.approx(0.8)
    with pytest.raises(ValueError, match="positive"):
        warn_probability_threshold(0.0)


def test_outcome_refuses_a_cost_that_is_not_positive():
    for bad in (0.0, -1.0, float("inf")):
        with pytest.raises(ValueError, match="false_alarm_cost"):
            Outcome(False, None, false_alarm_cost=bad)


def test_the_budget_stamps_its_cost_on_a_settled_false_alarm():
    budget = WarningBudget(false_alarm_cost=3.0)
    _, state = budget.admit(BudgetState(), 0, FAILED, pattern(1))
    _, lessons = budget.settle(state, 5, frozenset())
    assert [lesson.outcome.false_alarm_cost for lesson in lessons] == [3.0]
    assert not lessons[0].outcome.pain_point_followed
    capped = WarningBudget.for_budget(0.15, per_steps=20, false_alarm_cost=2.0)
    assert capped.false_alarm_cost == 2.0


@pytest.mark.parametrize("filler_type", [Mushroom, DenseNet], ids=IDS)
def test_the_calibrator_rate_is_a_fixed_setting_of_the_filler(filler_type):
    still, quick = (
        filler_type(seed=1, calibrator_rate=0.0),
        filler_type(seed=1, calibrator_rate=0.5),
    )
    calm = Outcome(pain_point_followed=False, signature=None)
    kept = still.learn(pattern(3), calm, still.initial_state(0)).calibrator
    moved = quick.learn(pattern(3), calm, quick.initial_state(0)).calibrator
    assert kept == Calibrator()
    assert moved.bias < 0
