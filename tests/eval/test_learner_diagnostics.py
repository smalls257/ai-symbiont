import numpy as np
import pytest

from symbiont.core.dense_variants import DenseVariant
from symbiont.core.fly_variants import FlyVariant
from symbiont.core.input_gain import fit_input_gain
from symbiont.eval.learner_diagnostics import (
    cell_memory,
    fly_code_report,
    memory_updates,
    saturation_share,
)


def test_memory_is_one_over_rate_without_trouble_and_with_full_relax():
    assert memory_updates(0.01, 1.0, 0.0) == pytest.approx(-1 / np.log1p(-0.01))


def test_smaller_rate_remembers_longer():
    assert memory_updates(0.01, 0.05, 0.18) > 9 * memory_updates(0.1, 0.05, 0.18)


def test_cell_memory_counts_updates_per_cell():
    codes = np.array([[0, 1], [0, 2]])
    report = cell_memory(codes, np.array([True, False]), 0.1, 0.05)
    assert report["median_updates_per_cell"] == 1.0
    assert 0 < report["median_share_of_outcomes_remembered"] <= 1


def test_a_large_input_takes_over_the_code_and_gain_undoes_it():
    rng = np.random.default_rng(0)
    rows = (rng.random((400, 86)) < 0.08).astype(float)
    rows[:, 85] = 6.0 * (rng.random(400) < 0.6)
    fly = FlyVariant(seed=0)
    raw = fly_code_report(fly, fly.initial_state(0), rows, watched=85)
    gained = FlyVariant(seed=0, gain=fit_input_gain(rows))
    fixed = fly_code_report(gained, gained.initial_state(0), rows, watched=85)
    assert raw["active_wired_to_watched_input_share_when_on"] > 0.9
    assert fixed["active_wired_to_watched_input_share_when_on"] < 0.6
    assert 0 <= raw["active_chosen_by_tie_break_share"] <= 1


def test_saturation_falls_with_gain():
    rng = np.random.default_rng(1)
    rows = (rng.random((200, 86)) < 0.1).astype(float)
    rows[:, 85] = rng.random(200) * 8
    plain = DenseVariant(seed=0)
    gained = DenseVariant(seed=0, gain=fit_input_gain(rows), hidden_scale=1 / np.sqrt(86))
    assert saturation_share(gained, gained.initial_state(0), rows) < saturation_share(
        plain, plain.initial_state(0), rows
    )
