import numpy as np

from symbiont.eval.note_cost_logistic import class_weights
from symbiont.eval.tanh_net import (
    NetScorer,
    fine_tune,
    fit_mlp,
    gradient,
    initial_net,
    weighted_loss,
)


def xor_data(n, seed):
    rng = np.random.default_rng(seed)
    rows = (rng.random((n, 6)) < 0.5).astype(float)
    labels = rows[:, 0] != rows[:, 1]
    return rows, labels


def test_gradient_matches_finite_differences():
    rows, labels = xor_data(30, 0)
    net = initial_net(rows, seed=1, hidden=4)
    net = net.with_vector(
        net.as_vector() + np.random.default_rng(2).normal(0, 0.3, len(net.as_vector()))
    )
    x, weights = net.gain.apply(rows), class_weights(labels)
    vector, analytic = net.as_vector(), gradient(net, x, labels, weights)
    for i in (0, 5, len(vector) - 7, len(vector) - 1):
        bump = np.zeros_like(vector)
        bump[i] = 1e-6
        up = weighted_loss(net.with_vector(vector + bump), x, labels, weights)
        down = weighted_loss(net.with_vector(vector - bump), x, labels, weights)
        assert np.isclose((up - down) / 2e-6 * len(x), analytic[i], rtol=1e-4, atol=1e-6)


def test_mlp_learns_a_rule_no_linear_model_can():
    net = fit_mlp(xor_data(30000, 3), xor_data(500, 4), seed=0)
    rows, labels = xor_data(500, 5)
    risk = NetScorer().step_risks(NetScorer().encode(rows, net), net)
    assert np.mean((risk > 0.5) == labels) > 0.9


def test_fine_tune_moves_toward_new_data_and_keeps_the_start():
    rows, labels = xor_data(200, 6)
    net = initial_net(rows, seed=0, hidden=4)
    weights = class_weights(labels)
    x = net.gain.apply(rows)
    tuned = fine_tune(net, rows, labels, weights, anchor=0.0)
    assert weighted_loss(tuned, x, labels, weights) < weighted_loss(net, x, labels, weights)
    held = fine_tune(net, rows, labels, weights, anchor=1e6)
    moved = np.linalg.norm(tuned.as_vector() - net.as_vector())
    assert np.linalg.norm(held.as_vector() - net.as_vector()) < moved / 2
    assert net.as_vector().shape == tuned.as_vector().shape
