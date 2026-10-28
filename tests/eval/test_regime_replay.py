import numpy as np
import pytest

from symbiont.eval.regime_replay import (
    Project,
    consolidation,
    frozen_risks,
    live_risks,
    refit_risks,
    train_online,
)


class Tally:
    """Risk is the share of trouble seen so far; encode is the identity."""

    def initial_state(self, seed):
        return (0, 0)

    def encode(self, rows, state):
        return rows

    def step_risks(self, encoded, state):
        seen, trouble = state
        return np.full(len(encoded), trouble / seen if seen else 0.0)

    def learn(self, encoded, followed, state):
        return state[0] + len(followed), state[1] + int(np.sum(followed))


def project():
    sessions = (
        (np.zeros((2, 1)), np.array([True, True])),
        (np.zeros((2, 1)), np.array([False, False])),
        (np.zeros((1, 1)), np.array([True])),
    )
    return Project("p", sessions)


def test_live_scores_each_session_before_learning_it():
    risks = live_risks(Tally(), project(), (0, 0))
    assert [r.tolist() for r in risks] == [[0.0, 0.0], [1.0, 1.0], [0.5]]


def test_frozen_never_learns():
    risks = frozen_risks(Tally(), project(), (4, 1))
    assert all(np.all(r == 0.25) for r in risks)


def test_refit_sees_only_earlier_sessions():
    seen = []

    def refit(encoded, followed):
        seen.append(len(encoded))
        return Tally().learn(None, np.concatenate(followed), (0, 0))

    risks = refit_risks(Tally(), refit, project(), (0, 0))
    assert seen == [1, 2]
    assert [r.tolist() for r in risks] == [[0.0, 0.0], [1.0, 1.0], [0.5]]


def test_one_pass_consolidation_is_the_live_rule():
    scorer = Tally()
    live = live_risks(scorer, project(), (0, 0))
    refit = refit_risks(scorer, consolidation(scorer, (0, 0), passes=1), project(), (0, 0))
    assert all(np.array_equal(a, b) for a, b in zip(live, refit, strict=True))


def test_train_online_runs_every_session():
    assert train_online(Tally(), [project(), project()], (0, 0)) == (10, 6)


def test_zero_passes_is_refused():
    with pytest.raises(ValueError, match="pass"):
        consolidation(Tally(), (0, 0), passes=0)
