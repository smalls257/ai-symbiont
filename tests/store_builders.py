"""Store builders for tests: put lessons in a store the way a finished mining would."""

from collections.abc import Iterable, Sequence

from symbiont.miner.lessons import Lesson
from symbiont.store.held_back import MiningOutcome
from symbiont.store.local import Source, Store


def save_lessons(
    store: Store,
    project: str,
    new_sources: Iterable[Source],
    lessons: Sequence[Lesson],
    *,
    held_out_tasks: frozenset[str],
) -> None:
    """Register `new_sources` and replace `project`'s lessons; nothing was held back.

    A finished mining records the `min_sessions` it screened with (1 here: the lessons are
    taken as screened), so the store reads as mined with today's rules, not as an older one.
    """
    outcome = MiningOutcome(list(lessons), min_sessions=1)
    store.mined.save(project, new_sources, outcome, held_out_tasks=held_out_tasks)
