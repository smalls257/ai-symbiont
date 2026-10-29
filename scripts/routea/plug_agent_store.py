"""The lesson store one PLUG-AGENT-1 task may see: only lessons mined from earlier instances.

Three rules, each counted: no lesson of round 3's 40 scored repos; none from the task's own
instance; none from an instance created after the task's (an undated instance is out). The
candidate list then matches round 3's items, so the thresholds keep their meaning: the repo's
remaining lessons plus other repos' lessons, sampled with the instance id as seed, up to
PROMPT_LESSONS. Pure.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lessons import Lesson
from plug_situation import PROMPT_LESSONS


@dataclass(frozen=True)
class Store:
    """The task's candidate lessons and how many lessons each rule removed."""

    candidates: tuple[Lesson, ...]
    removed_scored_repo: int
    removed_own_instance: int
    removed_later_or_undated: int


def _earlier(instance: str | None, cutoff: str, dates: Mapping[str, str | None]) -> bool:
    created = dates.get(instance) if instance else None
    return created is not None and created < cutoff


def store_for(
    task: Mapping[str, str],
    by_repo: Mapping[str, Sequence[Lesson]],
    instance_of: Mapping[str, str],
    dates: Mapping[str, str | None],
    scored_repos: frozenset[str],
) -> Store:
    """The store for `task` (instance_id, repo, created_at); KeyError if a field is missing."""
    own, cutoff = task["instance_id"], task["created_at"]
    kept: dict[str, list[Lesson]] = {}
    counts = {"scored": 0, "own": 0, "later": 0}
    for repo, lessons in by_repo.items():
        for lesson in lessons:
            instance = instance_of.get(lesson.lesson_id)
            if repo in scored_repos:
                counts["scored"] += 1
            elif instance == own:
                counts["own"] += 1
            elif not _earlier(instance, cutoff, dates):
                counts["later"] += 1
            else:
                kept.setdefault(repo, []).append(lesson)
    return Store(
        _candidates(kept, task["repo"], own), counts["scored"], counts["own"], counts["later"]
    )


def _candidates(kept: Mapping[str, list[Lesson]], repo: str, seed: str) -> tuple[Lesson, ...]:
    """The repo's lessons, then other repos' sampled by `seed`; PROMPT_LESSONS in all."""
    own = list(kept.get(repo, []))[:PROMPT_LESSONS]
    others = sorted(
        (lesson for name, found in kept.items() if name != repo for lesson in found),
        key=lambda lesson: lesson.lesson_id,
    )
    room = max(0, PROMPT_LESSONS - len(own))
    sample = random.Random(seed).sample(others, min(room, len(others)))
    return tuple(own + sample)
