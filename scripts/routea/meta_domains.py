"""Domains for the meta-learned starting adapter (METALORA): one public repo is one domain.

A held-out repo whose lessons leaked into meta-training would make the meta start look fast when
it only remembers: `split_domains` puts every repo in exactly one split (by a hash of its name)
and `check_held_out` raises on a shared repo or lesson, never filtering quietly.
Pure: lessons in, splits out.
"""

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lessons import Lesson
from meta_recipe import SIZES

# A held-out repo must hold max(SIZES) = 10 lessons so it can be taught every size.
MIN_HELD_OUT_LESSONS = max(SIZES)
# A meta-training domain needs 3 lessons (18 rows, four batches of 4) to make one inner loop.
MIN_TRAIN_LESSONS = 3
HELD_OUT_REPOS = 5  # dispatch: about 5 validation and 5 test repos


class HoldOutLeakError(ValueError):
    """A held-out repo or lesson reached meta-training."""


@dataclass(frozen=True)
class Split:
    """Repo name -> ordered lesson ids, per split. Sets nest: the first 5 ids are the 5-set."""

    train: dict[str, list[str]]
    val: dict[str, list[str]]
    test: dict[str, list[str]]


def distinct_lessons(candidates: Iterable[Lesson]) -> list[Lesson]:
    """One lesson per (repo, error class, fix) in lesson-id order, as LCAP picks them,
    without LCAP's two-per-repo cap: here a repo is meant to hold many lessons."""
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    kept = []
    for lesson in sorted(candidates, key=lambda item: item.lesson_id):
        key = (lesson.repo, lesson.error_class, lesson.added)
        if key not in seen:
            seen.add(key)
            kept.append(lesson)
    return kept


def _hashed(repo: str) -> str:
    return hashlib.sha1(repo.encode()).hexdigest()


def split_domains(lessons: Sequence[Lesson]) -> Split:
    """Repos with 10+ lessons, in hash order: the first 5 are test, the next 5 validation; every
    other repo with 3+ lessons is a meta-training domain. Raises ValueError when too few repos
    can be held out."""
    by_repo: dict[str, list[str]] = defaultdict(list)
    for lesson in sorted(lessons, key=lambda item: item.lesson_id):
        by_repo[lesson.repo].append(lesson.lesson_id)
    eligible = sorted(
        (r for r, ids in by_repo.items() if len(ids) >= MIN_HELD_OUT_LESSONS), key=_hashed
    )
    if len(eligible) < 2 * HELD_OUT_REPOS:
        raise ValueError(
            f"{len(eligible)} repos hold {MIN_HELD_OUT_LESSONS}+ lessons, need {2 * HELD_OUT_REPOS}"
        )
    test, val = eligible[:HELD_OUT_REPOS], eligible[HELD_OUT_REPOS : 2 * HELD_OUT_REPOS]
    held = set(test) | set(val)
    train = {
        r: ids
        for r, ids in sorted(by_repo.items())
        if r not in held and len(ids) >= MIN_TRAIN_LESSONS
    }
    split = Split(train, {r: by_repo[r] for r in val}, {r: by_repo[r] for r in test})
    check_held_out(split)
    return split


def check_held_out(split: Split) -> None:
    """Raise HoldOutLeakError when a validation or test repo or lesson is also a training one."""
    trained_ids = {i for ids in split.train.values() for i in ids}
    for name, held in (("val", split.val), ("test", split.test)):
        shared_repos = set(held) & set(split.train)
        shared_ids = trained_ids & {i for ids in held.values() for i in ids}
        if shared_repos or shared_ids:
            raise HoldOutLeakError(
                f"{name}: {len(shared_repos)} repos, {len(shared_ids)} lessons in train"
            )
    if set(split.val) & set(split.test):
        raise HoldOutLeakError("a repo is in both val and test")
