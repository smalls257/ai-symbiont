import numpy as np
import pytest

from symbiont.core.dense import DenseNet
from symbiont.core.dense_variants import DenseVariant, ReadoutInput
from symbiont.core.input_gain import fit_input_gain


def data(n, seed):
    rng = np.random.default_rng(seed)
    rows = (rng.random((n, 86)) < 0.1).astype(np.float64)
    rows[:, 85] = rng.random(n) * 7.0
    followed = rows[:, 3] > 0  # a linear rule on one flag
    return rows, followed


def log_loss(risk, followed):
    risk = np.clip(risk, 1e-9, 1 - 1e-9)
    return float(-np.mean(np.where(followed, np.log(risk), np.log(1 - risk))))


def test_default_hidden_layer_is_densenets():
    variant = DenseVariant(seed=4)
    assert np.array_equal(variant.initial_state(1).hidden_w, DenseNet(4).initial_state(1).hidden_w)


def test_risk_starts_at_one_half_and_learning_lowers_the_loss():
    variant = DenseVariant(seed=0, rate=1.0)
    rows, followed = data(400, 1)
    state = variant.initial_state(0)
    encoded = variant.encode(rows, state)
    assert np.allclose(variant.step_risks(encoded, state), 0.5)
    before = log_loss(variant.step_risks(encoded, state), followed)
    state = variant.learn(encoded, followed, state)
    assert log_loss(variant.step_risks(encoded, state), followed) < before


def test_learn_is_pure():
    variant = DenseVariant(seed=0)
    rows, followed = data(10, 2)
    state = variant.initial_state(0)
    before = state.readout.copy()
    variant.learn(variant.encode(rows, state), followed, state)
    assert np.array_equal(state.readout, before)


def test_skip_readout_sees_the_raw_inputs():
    plain = DenseVariant(seed=0, hidden=16)
    skip = DenseVariant(seed=0, hidden=16, readout_input=ReadoutInput.HIDDEN_AND_INPUTS)
    rows, _ = data(3, 3)
    assert plain.encode(rows, plain.initial_state(0)).shape == (3, 16)
    assert skip.encode(rows, skip.initial_state(0)).shape == (3, 16 + 86)


def test_trouble_weight_pushes_risk_up_on_trouble():
    rows, followed = data(300, 4)
    risks = []
    for weight in (1.0, 5.0):
        variant = DenseVariant(seed=0, trouble_weight=weight)
        state = variant.initial_state(0)
        encoded = variant.encode(rows, state)
        risks.append(variant.step_risks(encoded, variant.learn(encoded, followed, state)).mean())
    assert risks[1] > risks[0]


def test_decaying_rate_moves_less_late_than_early():
    variant = DenseVariant(seed=0, rate=1.0, rate_halflife=10.0)
    assert variant.rate_at(0) == 1.0
    assert variant.rate_at(10) == pytest.approx(0.5)


def test_gain_is_applied_before_the_hidden_layer():
    rows, _ = data(100, 5)
    gained = DenseVariant(seed=0, gain=fit_input_gain(rows))
    plain = DenseVariant(seed=0)
    a = gained.encode(rows[:2], gained.initial_state(0))
    b = plain.encode(rows[:2], plain.initial_state(0))
    assert not np.allclose(a, b)


def test_bad_settings_are_refused():
    with pytest.raises(ValueError, match="hidden"):
        DenseVariant(seed=0, hidden=0)
    with pytest.raises(ValueError, match="weight"):
        DenseVariant(seed=0, trouble_weight=0.0)
