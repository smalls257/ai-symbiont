"""The batch classifier row: a weighted, penalized fit whose selection risks are out of sample."""

import numpy as np
import pytest

from symbiont.eval.note_cost_logistic import (
    Steps,
    class_weights,
    fit_logistic,
    outer_fold_risks,
    predict,
)


def data(seed=0, n=600):
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(n, 4))
    labels = (features[:, 0] + 0.5 * rng.normal(size=n) > 1.0).astype(float)
    return features, labels


def test_class_weights_balance_the_two_classes_and_sum_to_the_step_count():
    labels = np.array([True] + [False] * 5)
    weights = class_weights(labels)
    assert weights[labels].sum() == pytest.approx(weights[~labels].sum())
    assert weights.sum() == pytest.approx(len(labels))


def test_one_class_only_is_refused():
    with pytest.raises(ValueError, match="both"):
        class_weights(np.zeros(5, dtype=bool))


def test_the_fit_ranks_trouble_above_calm_and_a_stronger_penalty_shrinks_it():
    features, labels = data()
    loose, tight = fit_logistic(features, labels, 0.1), fit_logistic(features, labels, 1e5)
    risk = predict(loose, features)
    assert risk[labels == 1].mean() > risk[labels == 0].mean() + 0.3
    assert np.abs(tight.coef[1:]).sum() < np.abs(loose.coef[1:]).sum()


def test_no_risk_ever_comes_from_a_model_that_saw_the_outer_fold():
    features, labels = data()
    step_fold = np.arange(len(labels)) % 5
    before = outer_fold_risks(Steps(features, labels, step_fold), outer=2, l2=1.0)
    flipped = labels.copy()
    flipped[step_fold == 2] = 1 - flipped[step_fold == 2]
    after = outer_fold_risks(Steps(features, flipped, step_fold), outer=2, l2=1.0)
    assert np.allclose(before, after)


def test_a_fit_mask_limits_what_the_models_learn_from():
    features, labels = data()
    step_fold = np.arange(len(labels)) % 5
    mask = np.arange(len(labels)) < 300
    before = outer_fold_risks(Steps(features, labels, step_fold), outer=0, l2=1.0, fit_mask=mask)
    changed = labels.copy()
    changed[~mask] = 1 - changed[~mask]  # steps outside the mask cannot move any risk
    after = outer_fold_risks(Steps(features, changed, step_fold), outer=0, l2=1.0, fit_mask=mask)
    assert np.allclose(before, after)
