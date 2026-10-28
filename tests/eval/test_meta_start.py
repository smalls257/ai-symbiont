"""Meta-training a filler's start across repositories (T39).

Violations prevented: **Paper Tiger** (a meta start that only looks better because it was
judged on its own training repositories, or a fast path that scores something other than
what the replay does) and **Silent Fallback** (a filler with no start trained to no effect).
"""

from dataclasses import replace

import numpy as np
import pytest

from record_builders import edit, run, say, session, view
from symbiont.core.counters import Counters
from symbiont.core.dense import DenseNet
from symbiont.core.meta import NotMetaLearnableError
from symbiont.core.mushroom import Mushroom
from symbiont.eval.meta_start import (
    EARLY_SESSIONS,
    Episode,
    MetaConfig,
    calibrated_risks,
    cold_start,
    early_loss,
    meta_split,
    meta_train,
    online_risks,
)
from symbiont.eval.offline import ReplayContext, Start, replay

FILLERS = [Mushroom(seed=1), DenseNet(seed=1, lr=0.1)]
IDS = ["fly", "dense"]
COST = 0.5


def trap_session(sid, task, failing):
    records = session(
        view("tests/test_a.py"),
        edit("pkg/a.py"),
        run("python -m pytest tests/test_a.py -q", 1 if failing else 0, "ImportError: x"),
        *[say("done") for _ in range(4)],
    )
    return [replace(r, session_id=sid, task_id=task) for r in records]


class Watcher:
    """Replays a filler and keeps each step's features and calibrated probability."""

    def __init__(self, filler):
        self.inner, self.name = filler, filler.name
        self.rows, self.risks = [], []

    def initial_state(self, seed):
        return self.inner.initial_state(seed)

    def decide(self, x, situation, state):
        self.rows.append(np.array(x, dtype=np.float64))
        self.risks.append(self.inner.trouble_probability(x, state))
        return self.inner.decide(x, situation, state)

    def learn(self, x, outcome, state):
        return self.inner.learn(x, outcome, state)


@pytest.mark.parametrize("filler", FILLERS, ids=IDS)
def test_the_fast_path_scores_exactly_what_the_replay_decides_from(filler):
    sessions = [trap_session(f"s{i}", f"t{i % 3}", failing=i % 2 == 0) for i in range(6)]
    watcher = Watcher(filler)
    ctx = ReplayContext({}, frozenset(), false_alarm_cost=COST)
    done = replay(watcher, sessions, Start.fresh(), ctx=ctx, seed=0)
    lengths = [len(s.followed) for s in done.scores.per_session]
    cuts = np.cumsum(lengths)[:-1]
    episode = Episode(
        "r",
        tuple(np.split(np.vstack(watcher.rows), cuts)),
        tuple(np.array(s.followed) for s in done.scores.per_session),
    )
    assert any(any(y) for y in episode.followed)
    fast = np.concatenate(online_risks(filler, cold_start(filler), episode, COST))
    np.testing.assert_allclose(fast, watcher.risks, rtol=0, atol=1e-12)


def toy_repo(name, seed, sessions=EARLY_SESSIONS + 2, steps=12):
    """Every repository shares one rule: feature 3 marks trouble ahead."""
    rng = np.random.default_rng(seed)
    xs, ys = [], []
    for _ in range(sessions):
        x = (rng.random((steps, 86)) < 0.15).astype(np.float64)
        y = x[:, 3] > 0
        xs.append(x)
        ys.append(y)
    return Episode(name, tuple(xs), tuple(ys))


@pytest.mark.parametrize("filler", FILLERS, ids=IDS)
def test_a_start_meta_trained_on_shared_structure_beats_the_cold_start_on_unseen_repos(filler):
    train = [toy_repo(f"train{i}", i) for i in range(6)]
    validation = [toy_repo(f"val{i}", 100 + i) for i in range(2)]
    unseen = [toy_repo(f"unseen{i}", 200 + i) for i in range(3)]
    config = MetaConfig(outer_rate=0.05, outer_steps=40, batch=3, check_every=10, cost=COST)
    result = meta_train(filler, train, validation, config)
    assert result.curve[0][0] == 0
    assert result.best_step > 0
    assert result.best_loss < result.curve[0][1]
    cold = early_loss(filler, cold_start(filler), unseen, COST)
    assert early_loss(filler, result.start, unseen, COST) < cold


def test_with_nothing_to_learn_the_cold_start_comes_back():
    filler = DenseNet(seed=1, lr=0.1)
    train = [toy_repo(f"train{i}", i) for i in range(3)]
    config = MetaConfig(outer_rate=0.0, outer_steps=20, batch=2, check_every=10, cost=COST)
    result = meta_train(filler, train, train[:1], config)
    assert result.best_step == 0
    np.testing.assert_array_equal(result.start.as_vector(), cold_start(filler).as_vector())


def test_counters_are_refused_by_name_and_empty_data_raises():
    with pytest.raises(NotMetaLearnableError, match="counters"):
        meta_train(Counters(), [toy_repo("a", 0)], [toy_repo("b", 1)], MetaConfig(0.1))
    with pytest.raises(ValueError, match="validation"):
        meta_train(DenseNet(seed=0), [toy_repo("a", 0)], [], MetaConfig(0.1))


def test_an_episode_whose_labels_do_not_line_up_raises():
    with pytest.raises(ValueError, match="feature rows"):
        Episode("r", (np.zeros((3, 86)),), (np.zeros(2, dtype=bool),))


def test_the_calibrated_classifier_starts_at_its_own_probabilities_and_adapts():
    probs = [np.full(20, 0.6), np.full(20, 0.6)]
    calm = [np.zeros(20, dtype=bool), np.zeros(20, dtype=bool)]
    first, second = calibrated_risks(probs, calm, COST)
    np.testing.assert_allclose(first, 0.6)
    assert (second < 0.6).all()
    assert len(set(second.round(12))) == 1  # within a session nothing is learned yet


def pool(n=100):
    return [{"repo": f"org/r{i:03d}", "fold": i % 5} for i in range(n)]


def test_the_split_scores_fold_zero_and_validates_on_ten_of_the_rest_every_time():
    split = meta_split(pool())
    assert split == meta_split(pool())
    assert len(split.scoring) == 20 and len(split.validation) == 10 and len(split.train) == 70
    assert not set(split.validation) & (set(split.train) | set(split.scoring))
    assert not set(split.train) & set(split.scoring)


def test_a_held_out_repository_in_the_pool_is_refused():
    with pytest.raises(ValueError, match="held-out"):
        meta_split([*pool(), {"repo": "iterative/dvc", "fold": 1}])
