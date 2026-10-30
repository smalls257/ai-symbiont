"""PLUG-AGENT-2 inference: the sign-flip test on the mean and the BCa interval."""

import sys
from pathlib import Path

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
sys.path.insert(0, str(ROUTEA))

from plug_agent2_stats import bca_interval, cluster_means, sign_flip_p  # noqa: E402


def test_exact_sign_flip_matches_hand_count():
    # four equal positive differences: only all-plus and all-minus reach the observed mean
    assert sign_flip_p([0.2, 0.2, 0.2, 0.2]) == 2 / 16


def test_all_zero_differences_are_a_tie_with_p_one():
    assert sign_flip_p([0.0] * 10) == 1.0


def test_balanced_differences_are_not_significant_and_shifted_ones_are():
    assert sign_flip_p([0.3, -0.3, 0.2, -0.2, 0.1, -0.1]) == 1.0
    assert sign_flip_p([0.25 + 0.01 * i for i in range(30)]) < 0.001


def test_random_flip_branch_is_reproducible():
    diffs = [(-1) ** i * 0.1 + 0.05 for i in range(40)]
    assert sign_flip_p(diffs) == sign_flip_p(diffs)


def test_bca_interval_brackets_the_mean_and_is_reproducible():
    diffs = [0.1, 0.3, 0.2, 0.4, 0.0, 0.2, 0.3, 0.1, 0.25, 0.15]
    low, high = bca_interval(diffs, resamples=2000)
    assert low < sum(diffs) / len(diffs) < high
    assert (low, high) == bca_interval(diffs, resamples=2000)


def test_bca_interval_excludes_zero_for_a_clear_shift():
    low, _ = bca_interval([0.2 + 0.02 * (i % 5) for i in range(40)], resamples=2000)
    assert low > 0


def test_cluster_means_average_points_that_share_a_key():
    assert cluster_means([1.0, 0.0, 0.5], ["a", "a", "b"]) == [0.5, 0.5]
