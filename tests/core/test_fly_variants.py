import numpy as np
import pytest

from symbiont.core.fly_variants import FlyVariant, Valence
from symbiont.core.input_gain import fit_input_gain
from symbiont.core.mushroom import N_ACTIVE, Mushroom, kc_code
from symbiont.core.slot import Outcome


def sparse_rows(n, seed):
    rng = np.random.default_rng(seed)
    rows = (rng.random((n, 86)) < 0.1).astype(np.float64)
    rows[:, 85] = rng.random(n) * 7.0  # a log-count input among 0/1 flags
    return rows


def labels(n, seed):
    return np.random.default_rng(seed + 100).random(n) < 0.2


def test_codes_are_the_existing_flys_cells():
    fly, rows = FlyVariant(seed=3), sparse_rows(20, 0)
    state = fly.initial_state(1)
    wiring = Mushroom(3).initial_state(1)
    for row, cells in zip(rows, fly.encode(rows, state), strict=True):
        assert len(cells) == N_ACTIVE
        assert set(cells.tolist()) == set(np.flatnonzero(kc_code(row, wiring)).tolist())


def test_default_variant_reproduces_the_existing_fly_exactly():
    fly, mushroom = FlyVariant(seed=2), Mushroom(2, lr=0.1)
    state, reference = fly.initial_state(0), mushroom.initial_state(0)
    for session in range(4):
        rows, followed = sparse_rows(15, session), labels(15, session)
        codes = fly.encode(rows, state)
        expected = [1.0 - reference.w_out[kc_code(r, reference)].mean() for r in rows]
        assert np.allclose(fly.step_risks(codes, state), expected, atol=1e-12)
        state = fly.learn(codes, followed, state)
        for row, hit in zip(rows, followed, strict=True):
            outcome = Outcome(bool(hit), None, false_alarm_cost=0.5)
            reference = mushroom.learn(row, outcome, reference)
    assert np.allclose(state.approach[0], reference.w_out, atol=1e-12)


def test_learn_is_pure():
    fly = FlyVariant(seed=1, rates=(0.1, 0.01), valence=Valence.TWO_VALENCE)
    state = fly.initial_state(0)
    rows = sparse_rows(5, 1)
    before = state.approach.copy(), state.avoid.copy()
    fly.learn(fly.encode(rows, state), np.ones(5, bool), state)
    assert np.array_equal(state.approach, before[0]) and np.array_equal(state.avoid, before[1])


def test_slow_compartment_remembers_longer_than_the_fast_one():
    fly = FlyVariant(seed=1, rates=(0.1, 0.01))
    state = fly.initial_state(0)
    codes = fly.encode(sparse_rows(1, 4), state)
    state = fly.learn(codes, np.array([True]), state)
    for _ in range(300):
        state = fly.learn(codes, np.array([False]), state)
    fast_left, slow_left = 1 - state.approach[0, codes[0]], 1 - state.approach[1, codes[0]]
    assert slow_left.mean() / 0.01 > fast_left.mean() / 0.1


def test_two_valence_learns_that_a_pattern_is_safe():
    fly = FlyVariant(seed=1, valence=Valence.TWO_VALENCE)
    state = fly.initial_state(0)
    safe, other = (fly.encode(sparse_rows(1, s), state) for s in (5, 6))
    start = fly.step_risks(safe, state)[0]
    for _ in range(50):
        state = fly.learn(safe, np.array([False]), state)
    assert fly.step_risks(safe, state)[0] < start - 0.1
    one_sided = FlyVariant(seed=1)
    flat = one_sided.initial_state(0)
    for _ in range(50):
        flat = one_sided.learn(safe, np.array([False]), flat)
    assert one_sided.step_risks(safe, flat)[0] == pytest.approx(0.0)
    assert fly.step_risks(other, state)[0] <= start


def test_gain_changes_which_cells_fire():
    rows = sparse_rows(200, 7)
    plain = FlyVariant(seed=1)
    gained = FlyVariant(seed=1, gain=fit_input_gain(rows))
    a, b = (
        plain.encode(rows[:5], plain.initial_state(0)),
        gained.encode(rows[:5], gained.initial_state(0)),
    )
    assert any(set(x.tolist()) != set(y.tolist()) for x, y in zip(a, b, strict=True))


def test_no_compartment_is_refused():
    with pytest.raises(ValueError, match="compartment"):
        FlyVariant(seed=0, rates=())
