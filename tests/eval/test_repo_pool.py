"""The cross-repository pool: a pure, seeded rule that never admits a held-out repository."""

import pytest

from symbiont.eval.repo_pool import (
    EXCLUDED,
    HELD_OUT,
    MAX_TRAJECTORIES,
    POOL_REPOS,
    build_pool,
    capped_tasks,
)


def counts(n_repos=130):
    table = {
        f"org/repo{i:03d}": {f"r{i}-t{j}": 1 + (i + j) % 7 for j in range(12)}
        for i in range(n_repos)
    }
    for repo in (*HELD_OUT, *EXCLUDED):
        table[repo] = {f"{repo}-t{j}": 5 for j in range(40)}
    return table


def test_held_out_and_excluded_repositories_never_enter_the_pool():
    pool = build_pool(counts())
    names = {entry["repo"] for entry in pool["repos"]}
    assert not names & {*HELD_OUT, *EXCLUDED}
    assert len(names) == POOL_REPOS


def test_the_pool_is_the_same_every_time_and_caps_each_repository():
    first, second = build_pool(counts()), build_pool(counts())
    assert first == second
    assert all(entry["trajectories"] <= MAX_TRAJECTORIES for entry in first["repos"])
    assert {entry["fold"] for entry in first["repos"]} == {0, 1, 2, 3, 4}


def test_whole_tasks_are_kept_and_one_task_is_always_kept():
    assert capped_tasks({"a": 80}, seed=1) == ["a"]
    kept = capped_tasks({"a": 30, "b": 30, "c": 10}, seed=1)
    assert sum({"a": 30, "b": 30, "c": 10}[t] for t in kept) <= MAX_TRAJECTORIES


def test_too_few_eligible_repositories_is_refused_not_shrunk():
    with pytest.raises(ValueError, match="eligible"):
        build_pool(counts(n_repos=10))
