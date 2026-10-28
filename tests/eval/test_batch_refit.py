import numpy as np
import pytest

from symbiont.core.dense_variants import DenseVariant, ReadoutInput
from symbiont.core.input_gain import fit_input_gain
from symbiont.eval.batch_refit import (
    LogisticScorer,
    dense_as_net,
    map_logistic,
    refit_readout,
    trouble_weights,
)
from symbiont.eval.note_cost_logistic import fit_logistic, predict
from symbiont.eval.tanh_net import NetScorer


def data(n, seed):
    rng = np.random.default_rng(seed)
    rows = (rng.random((n, 86)) < 0.1).astype(float)
    return rows, rows[:, 2] > 0


def test_strong_prior_keeps_the_shipped_weights_and_a_weak_one_fits_the_data():
    rows, labels = data(300, 0)
    design = np.hstack([np.ones((300, 1)), rows])
    prior = np.zeros(87)
    weights = np.ones(300)
    held = map_logistic(design, labels.astype(float), weights, prior, 1e9)
    fitted = map_logistic(design, labels.astype(float), weights, prior, 0.1)
    assert np.allclose(held, prior, atol=1e-6)
    assert fitted[3] > 1.0


def test_refit_is_defined_without_any_trouble():
    rows, _ = data(50, 1)
    design = np.hstack([np.ones((50, 1)), rows])
    coef = map_logistic(design, np.zeros(50), np.ones(50), np.ones(87), 10.0)
    assert np.all(np.isfinite(coef))


def test_a_non_positive_prior_is_refused():
    with pytest.raises(ValueError, match="prior"):
        map_logistic(np.ones((2, 1)), np.zeros(2), np.ones(2), np.zeros(1), 0.0)


def test_logistic_scorer_matches_the_shipped_model():
    rows, labels = data(400, 2)
    rows[:, 5] = 1.0  # an input that never varies
    model = fit_logistic(rows, labels, 10.0)
    scorer = LogisticScorer(model)
    assert np.allclose(
        scorer.step_risks(scorer.encode(rows, model.coef), model.coef), predict(model, rows)
    )


def test_trouble_weights_follow_the_training_share():
    weights = trouble_weights(np.array([True, False]), 0.2)
    assert weights.tolist() == pytest.approx([2.5, 0.625])


def test_readout_refit_moves_toward_the_project():
    rows, labels = data(300, 3)
    variant = DenseVariant(seed=0)
    shipped = variant.initial_state(0)
    encoded = variant.encode(rows, shipped)
    refit = refit_readout(variant, shipped, encoded, labels)
    before = variant.step_risks(encoded, shipped)
    after = variant.step_risks(encoded, refit)
    assert (
        after[labels].mean() - after[~labels].mean()
        > before[labels].mean() - before[~labels].mean()
    )


@pytest.mark.parametrize("readout", list(ReadoutInput))
def test_dense_as_net_is_the_same_function(readout):
    rows, labels = data(200, 4)
    variant = DenseVariant(seed=1, rate=1.0, readout_input=readout, gain=fit_input_gain(rows))
    state = variant.initial_state(0)
    encoded = variant.encode(rows, state)
    state = variant.learn(encoded, labels, state)
    net = dense_as_net(variant, state)
    assert np.allclose(
        NetScorer().step_risks(NetScorer().encode(rows, net), net),
        variant.step_risks(encoded, state),
    )
