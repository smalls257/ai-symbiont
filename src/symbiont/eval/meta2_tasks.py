"""META2 data: one trajectory per task, tasks by issue date, repositories split from counts alone.

The question is whether a learner improves on a repository's NEW issues after its earlier ones,
so each task gives one trajectory, replayed in the order issues were opened. The split is a pure
function of task counts and of the repositories earlier runs read, fixed before any row is read:
a scored repository was never read before and has enough tasks for a late window.
"""

import hashlib
import random
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from symbiont.eval.repo_pool import EXCLUDED, UNREADABLE

SEED = 20261029  # the project's run seed (symbiont.eval.selection.SEED)
# Scored before (T46: Pillow, dvc, conan; T48: tox, dask, PyBaMM): burnt for any selection.
SCORED_BEFORE = (
    "python-pillow/Pillow",
    "iterative/dvc",
    "conan-io/conan",
    "tox-dev/tox",
    "dask/dask",
    "pybamm-team/PyBaMM",
)
EARLY_TASKS = 10  # the owner's early window: a repository's first ten tasks
MIN_SCORED_TASKS = 2 * EARLY_TASKS  # a late window at least as long as the early one
HELD_OUT_REPOS = 12  # of the fresh repositories; the rest of them validate
MIN_TRAIN_TASKS = 5  # repo_pool.MIN_TASKS: fewer says little about a project
MAX_TRAIN_TASKS = 50  # per training repository, the first by issue date, so no project dominates
PICKS_PER_TASK = 2  # trajectories exported per task: the first in seeded order, one spare


class MissingIssueDateError(ValueError):
    """A task has no issue creation date, so its place in the repository's order is unknown."""


class NoReadableTrajectoryError(ValueError):
    """Every exported trajectory of a task was refused by the reader."""


@dataclass(frozen=True)
class Split:
    """Repositories by role; held-out ones are declared in the prereg before any metric."""

    held_out: tuple[str, ...]
    validation: tuple[str, ...]
    train: tuple[str, ...]

    def role_of(self, repo: str) -> str:
        """`held_out`, `validation` or `train`; raises for a repository outside the split."""
        for role in ("held_out", "validation", "train"):
            if repo in getattr(self, role):
                return role
        raise KeyError(f"{repo} is in no META2 role")


def blocked() -> frozenset[str]:
    """Repositories META2 never reads: scored before, excluded, or refused by the reader."""
    return frozenset(SCORED_BEFORE) | frozenset(EXCLUDED) | frozenset(UNREADABLE)


def split_repos(task_counts: Mapping[str, int], seen: Collection[str]) -> Split:
    """Fresh repositories with enough tasks, shuffled: the first held out, the rest validate.

    `seen` names every repository an earlier run read (the pool exports); those can train but
    never score. Raises if there are too few fresh repositories to hold out and validate.
    """
    usable = {r: n for r, n in task_counts.items() if r not in blocked()}
    fresh = sorted(r for r, n in usable.items() if n >= MIN_SCORED_TASKS and r not in seen)
    if len(fresh) <= HELD_OUT_REPOS:
        raise ValueError(f"{len(fresh)} fresh repositories, need more than {HELD_OUT_REPOS}")
    random.Random(SEED).shuffle(fresh)
    held, valid = tuple(fresh[:HELD_OUT_REPOS]), tuple(sorted(fresh[HELD_OUT_REPOS:]))
    scoring = set(held) | set(valid)
    train = tuple(sorted(r for r, n in usable.items() if n >= MIN_TRAIN_TASKS and r not in scoring))
    return Split(tuple(sorted(held)), valid, train)


def trajectory_rank(trajectory_id: str) -> str:
    """A seeded, order-free rank: the dataset records no attempt order within a task."""
    return hashlib.sha256(f"{SEED}:{trajectory_id}".encode()).hexdigest()


def picks(trajectory_ids: Sequence[str]) -> list[str]:
    """The trajectories exported for one task, best rank first."""
    return sorted(trajectory_ids, key=trajectory_rank)[:PICKS_PER_TASK]


def first_readable(task: str, ranked: Sequence[str], readable: Collection[str]) -> str:
    """The task's one trajectory: the best-ranked one the reader accepts."""
    for trajectory in ranked:
        if trajectory in readable:
            return trajectory
    raise NoReadableTrajectoryError(f"{task}: none of {len(ranked)} trajectories is readable")


def by_issue_date(tasks: Collection[str], created_at: Mapping[str, str]) -> list[str]:
    """Tasks in the order their issues were created (ties by task id)."""
    missing = sorted(t for t in tasks if not created_at.get(t))
    if missing:
        raise MissingIssueDateError(f"{len(missing)} task(s) without a date, first {missing[0]}")
    return sorted(tasks, key=lambda task: (created_at[task], task))


def kept_tasks(role: str, ordered: Sequence[str]) -> list[str]:
    """Every task of a scored repository; the first MAX_TRAIN_TASKS of a training one."""
    return list(ordered) if role != "train" else list(ordered[:MAX_TRAIN_TASKS])
