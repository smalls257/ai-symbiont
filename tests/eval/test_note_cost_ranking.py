"""Threshold-free ranking quality of a risk."""

import numpy as np
import pytest

from symbiont.eval.note_cost_ranking import ranking, roc_auc, top_share_precision


def test_perfect_random_and_reversed_rankings():
    labels = np.array([0, 0, 1, 1], dtype=bool)
    assert roc_auc(np.array([0.1, 0.2, 0.8, 0.9]), labels) == 1.0
    assert roc_auc(np.array([0.5, 0.5, 0.5, 0.5]), labels) == 0.5
    assert roc_auc(np.array([0.9, 0.8, 0.2, 0.1]), labels) == 0.0


def test_auc_needs_both_kinds_of_step():
    with pytest.raises(ValueError, match="both"):
        roc_auc(np.array([0.1, 0.2]), np.array([True, True]))


def test_precision_among_the_riskiest_steps():
    risks = np.arange(10.0)
    labels = np.array([0] * 8 + [1, 1], dtype=bool)
    assert top_share_precision(risks, labels, 0.2) == 1.0
    assert ranking(risks, labels)["base_rate"] == 0.2
