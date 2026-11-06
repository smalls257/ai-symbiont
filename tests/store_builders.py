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
    """Register `new_sources` and replace `project`'s lessons; nothing was held back."""
    store.mined.save(
        project, new_sources, MiningOutcome(list(lessons)), held_out_tasks=held_out_tasks
    )
