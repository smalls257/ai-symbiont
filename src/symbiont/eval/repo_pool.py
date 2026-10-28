"""The cross-repository training pool (T46 learning curve; reused unchanged by T39).

Each pool repository is one unit: T46 trains on some and scores on others, T39 treats each
as one meta-training task. The rule is a pure function of the per-(repo, task) trajectory
counts, so anyone with the counts rebuilds the same pool. The held-out repositories are
fixed here before any of their rows was read, and the exporter refuses them.
"""

import random
import zlib
from collections.abc import Mapping
from typing import Any

# Scored later on their own (docs/design/2026-10-28-note-cost.md): never exported for training.
HELD_OUT = ("python-pillow/Pillow", "iterative/dvc", "conan-io/conan")
# Its T36 test split must not be read, and its TRAIN split is already the T36/T46 data.
EXCLUDED = ("tobymao/sqlglot",)
# Repositories whose export the OpenHands reader refuses (found at the first export, 2026-10-28).
UNREADABLE = {"keras-team/keras-cv": "a tool call without 'command' (ReadError, line 4)"}
POOL_SEED = 20261029
POOL_REPOS = 100  # variety: a hundred projects
MIN_TASKS = 5  # a repository with fewer tasks says little about its own project
MIN_TRAJECTORIES = 20
MAX_TRAJECTORIES = 50  # per repository, whole tasks only; caps the run near two hours
REPO_FOLDS = 5  # fold 0 is the T46 scoring fold; T39 may use all five


def eligible(counts: Mapping[str, Mapping[str, int]]) -> list[str]:
    """Repositories big enough to say something, minus the held-out and excluded ones."""
    blocked = set(HELD_OUT) | set(EXCLUDED) | set(UNREADABLE)
    return sorted(
        repo
        for repo, tasks in counts.items()
        if repo not in blocked
        and len(tasks) >= MIN_TASKS
        and sum(tasks.values()) >= MIN_TRAJECTORIES
    )


def capped_tasks(tasks: Mapping[str, int], seed: int) -> list[str]:
    """Whole tasks in a seeded order while the trajectories stay within the cap."""
    order = sorted(tasks)
    random.Random(seed).shuffle(order)
    kept: list[str] = []
    total = 0
    for task in order:
        if kept and total + tasks[task] > MAX_TRAJECTORIES:
            continue
        kept.append(task)
        total += tasks[task]
    return sorted(kept)


def build_pool(counts: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    """The pool: repositories in a seeded order with their fold, tasks and trajectory count.

    Raises if fewer than POOL_REPOS repositories are eligible, rather than shrinking quietly.
    """
    candidates = eligible(counts)
    if len(candidates) < POOL_REPOS:
        raise ValueError(f"{len(candidates)} eligible repositories, the pool needs {POOL_REPOS}")
    random.Random(POOL_SEED).shuffle(candidates)
    repos = []
    for position, repo in enumerate(candidates[:POOL_REPOS]):
        tasks = capped_tasks(counts[repo], POOL_SEED + zlib.crc32(repo.encode()))
        trajectories = sum(counts[repo][t] for t in tasks)
        repos.append(
            {
                "repo": repo,
                "fold": position % REPO_FOLDS,
                "tasks": tasks,
                "trajectories": trajectories,
            }
        )
    return {
        "rule": (
            f"seeded shuffle of repos with >= {MIN_TASKS} tasks and >= {MIN_TRAJECTORIES} "
            f"trajectories, first {POOL_REPOS}, whole tasks up to {MAX_TRAJECTORIES} each"
        ),
        "seed": POOL_SEED,
        "held_out": list(HELD_OUT),
        "excluded": list(EXCLUDED),
        "unreadable": dict(UNREADABLE),
        "eligible_repos": len(candidates),
        "repo_folds": REPO_FOLDS,
        "repos": repos,
    }
