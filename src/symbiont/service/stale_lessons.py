"""Keep a store mined before the known-fix rule from speaking, and say so once.

The rule runs at mining time, so an older store still holds reworked-edit lessons and failed
commands the screen would now hold. Dropping them silently would look like missing history;
one warning per process names the cure.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Protocol

from symbiont.miner.lessons import Lesson
from symbiont.miner.screen import ScreenRules, taught_since_the_fix_rule
from symbiont.store.local import Store
from symbiont.store.mining import screening_of

log = logging.getLogger("symbiont.service")


class LessonSource(Protocol):
    """The store, or its remote view: whatever answers with a project's lessons."""

    def lessons(self, project: str) -> list[Lesson]:
        """The project's stored lessons."""


class StaleLessons:
    """Filters stored lessons down to the ones delivery may speak, warning once per instance."""

    def __init__(self, store: Store, current_rules: Callable[[], ScreenRules]) -> None:
        """Start before any warning has been given; `current_rules` are the developer's settings."""
        self._store = store
        self._current_rules = current_rules
        self._warned = False

    def deliverable(self, source: LessonSource, project: str) -> list[Lesson]:
        """`project`'s lessons without those an older mining kept; warns once when any dropped."""
        lessons = source.lessons(project)
        kept = screened_now(self._store, project, lessons, self._current_rules())
        if len(kept) < len(lessons) and not self._warned:
            self._warned = True
            log.warning(
                "this store was mined before the known-fix rule; %d stored lessons are not "
                "delivered. Run `symbiont repo mine` to refresh it.",
                len(lessons) - len(kept),
            )
        return kept


def screened_now(
    store: Store, project: str, lessons: Sequence[Lesson], current: ScreenRules
) -> list[Lesson]:
    """`lessons` as the screen keeps them today, under the rules the store was mined with."""
    return taught_since_the_fix_rule(lessons, screening_of(store, project, current))
