"""META2: one trajectory per task in issue order, a sequential replay, value per window.

Violations prevented: **Paper Tiger** (a learner scored on a task it already learned from, a
held-out repository an earlier run read, or a fast fly map that is not the fly's rule) and
**Silent Fallback** (an undated task or an unreadable task dropped without a word, a
classifier that "scores" before it has seen both labels).
"""

import numpy as np
import pytest

from symbiont.core.dense_variants import DenseVariant
from symbiont.core.fly_variants import FlyVariant, FlyVariantState, Valence
from symbiont.core.meta import Calibrator
from symbiont.eval import meta2_report as rep
from symbiont.eval import meta2_tasks as mt
from symbiont.eval.meta2_fly_map import apply_map, task_map
from symbiont.eval.meta2_replay import (
    SILENT,
    DenseRaw,
    FlyRaw,
    RepoTasks,
    calibrated_task,
    calibrator_after,
    own_logistic_risks,
    refit_logistic_risks,
    sequential_risks,
)
from symbiont.eval.note_cost_logistic import fit_logistic, predict


def counts_table(fresh: int, other: int) -> dict[str, int]:
    table = {f"fresh/r{i:02d}": 20 + i for i in range(fresh)}
    table.update({f"seen/r{i:02d}": 30 for i in range(other)})
    table.update({"small/one": 4, "mid/one": 7, "python-pillow/Pillow": 126})
    return table


def test_split_holds_out_only_fresh_repositories_with_a_late_window():
    table = counts_table(fresh=15, other=3)
    seen = {f"seen/r{i:02d}" for i in range(3)}
    split = mt.split_repos(table, seen)
    assert len(split.held_out) == mt.HELD_OUT_REPOS
    assert len(split.validation) == 15 - mt.HELD_OUT_REPOS
    scoring = set(split.held_out) | set(split.validation)
    assert all(r.startswith("fresh/") for r in scoring)
    assert seen <= set(split.train) and "mid/one" in split.train
    assert "small/one" not in split.train and "python-pillow/Pillow" not in split.train
    assert split == mt.split_repos(table, seen)
    assert split.role_of("mid/one") == "train"
    with pytest.raises(KeyError):
        split.role_of("small/one")


def test_split_refuses_too_few_fresh_repositories():
    with pytest.raises(ValueError, match="fresh repositories"):
        mt.split_repos(counts_table(fresh=mt.HELD_OUT_REPOS, other=0), set())


def test_one_trajectory_per_task_is_seeded_and_readable():
    ids = [f"chatcmpl-{i}" for i in range(9)]
    picked = mt.picks(ids)
    assert len(picked) == mt.PICKS_PER_TASK and picked == mt.picks(list(reversed(ids)))
    assert mt.first_readable("t", picked, {picked[1]}) == picked[1]
    with pytest.raises(mt.NoReadableTrajectoryError):
        mt.first_readable("t", picked, set())


def test_tasks_follow_issue_dates_and_an_undated_task_raises():
    created = {"a-2": "2024-01-02", "a-1": "2024-03-01", "a-3": "2024-01-02"}
    assert mt.by_issue_date(created, created) == ["a-2", "a-3", "a-1"]
    with pytest.raises(mt.MissingIssueDateError):
        mt.by_issue_date(["a-9"], created)
    ordered = [f"t{i}" for i in range(60)]
    assert len(mt.kept_tasks("train", ordered)) == mt.MAX_TRAIN_TASKS
    assert mt.kept_tasks("held_out", ordered) == ordered


@pytest.mark.parametrize("valence", list(Valence))
def test_fly_task_map_is_the_fly_rule(valence):
    rng = np.random.default_rng(3)
    fly = FlyVariant(0, rates=(0.1, 0.01), valence=valence)
    state = fly.initial_state(0)
    state = FlyVariantState(
        state.wiring, rng.random(state.approach.shape), rng.random(state.avoid.shape)
    )
    codes = fly.encode((rng.random((40, 86)) < 0.2).astype(float), state)
    followed = rng.random(40) < 0.3
    learned, mapped = (
        fly.learn(codes, followed, state),
        apply_map(state, task_map(fly, codes, followed), 40),
    )
    assert np.allclose(learned.approach, mapped.approach, atol=1e-14)
    assert np.allclose(learned.avoid, mapped.avoid, atol=1e-14)
    assert mapped.updates == learned.updates


def synthetic_repo(tasks: int = 4, steps: int = 12, seed: int = 0) -> RepoTasks:
    rng = np.random.default_rng(seed)
    features = tuple((rng.random((steps, 86)) < 0.3).astype(float) for _ in range(tasks))
    followed = tuple(x[:, 0] > 0.5 for x in features)  # trouble follows feature 0
    boundary = tuple(np.ones(steps, dtype=bool) for _ in range(tasks))
    return RepoTasks(
        "org/repo", tuple(f"org__repo-{i}" for i in range(tasks)), features, followed, boundary
    )


@pytest.mark.parametrize("rule", [FlyRaw(FlyVariant(0)), DenseRaw(DenseVariant(0, hidden=16))])
def test_each_task_is_decided_before_it_is_learned(rule):
    repo = synthetic_repo()
    state = (rule.fly if isinstance(rule, FlyRaw) else rule.dense).initial_state(0)
    encoded = [rule.encode(x, state) for x in repo.features]
    calibrator = Calibrator(1.5, -0.5)
    risks = sequential_risks(rule, (state, calibrator), encoded, repo)
    assert np.allclose(risks[0], calibrated_task(rule.raw(encoded[0], state), calibrator))
    after = rule.learn(encoded[0], repo.followed[0], state)
    moved = calibrator_after(calibrator, rule.raw(encoded[0], state), repo.followed[0], 0.05)
    assert np.allclose(risks[1], calibrated_task(rule.raw(encoded[1], after), moved))


def test_own_classifier_is_silent_until_it_has_seen_both_labels():
    repo = synthetic_repo(tasks=3)
    calm = RepoTasks(
        repo.repo,
        repo.task_ids,
        repo.features,
        (np.zeros(12, bool), *repo.followed[1:]),
        repo.boundary,
    )
    risks, silent = own_logistic_risks(calm)
    assert silent == 2 and np.all(risks[0] == SILENT) and np.all(risks[1] == SILENT)
    assert np.all((risks[2] > 0) & (risks[2] < 1))


def test_refit_classifier_starts_from_the_broad_fit():
    repo = synthetic_repo(tasks=3, seed=1)
    rows, labels = np.vstack(repo.features), np.concatenate(repo.followed).astype(float)
    broad = fit_logistic(rows, labels, 1000.0)
    risks = refit_logistic_risks(repo, broad, float(labels.mean()))
    assert np.allclose(risks[0], predict(broad, repo.features[0]))
    assert len(risks) == 3


def test_windows_split_a_repository_at_its_tenth_task():
    repo = synthetic_repo(tasks=13, steps=6)
    traces = rep.task_traces(repo, [np.full(6, 0.5)] * 13)
    assert len(rep.in_window(traces, rep.Window.EARLY)) == mt.EARLY_TASKS
    assert len(rep.in_window(traces, rep.Window.LATE)) == 3
    assert len(rep.in_window(traces, rep.Window.ALL)) == 13
    with pytest.raises(ValueError, match="risks for"):
        rep.task_traces(repo, [np.full(6, 0.5)] * 12)


def test_a_perfect_ranker_earns_and_differences_are_paired():
    repo = synthetic_repo(tasks=12, steps=10, seed=2)
    option = rep.primary_option()
    perfect = [y.astype(float) for y in repo.followed]
    traces = {0: {repo.repo: rep.task_traces(repo, perfect)}}
    at = {0: rep.choose_thresholds(traces[0], option)}
    early = rep.window_counts(traces, at, rep.Window.EARLY, option)
    assert rep.net(early, option) > 0
    assert rep.difference(early, early, option)["standing"] == "tie"
    late = rep.window_counts(traces, at, rep.Window.LATE, option)
    with pytest.raises(ValueError, match="different tasks"):
        rep.difference(early, late, option)


def test_share_of_in_domain_gain():
    assert rep.share_recovered(0.3, 0.1, 0.5) == pytest.approx(0.5)
    assert rep.share_recovered(0.3, 0.2, 0.1) is None
