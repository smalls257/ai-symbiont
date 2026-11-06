"""Keep a store mined before the known-fix rule from speaking, and say so once.

The rule runs at mining time, so an older store still holds reworked-edit lessons and failed
commands whose only "fix" was a re-run. Dropping them silently would look like missing history;
one warning per process names the cure.
"""

import logging
from collections.abc import Sequence

from symbiont.miner.lessons import Lesson
from symbiont.miner.screen import taught_since_the_fix_rule

log = logging.getLogger("symbiont.service")


class StaleLessons:
    """Filters stored lessons down to the ones delivery may speak, warning once per instance."""

    def __init__(self) -> None:
        """Start before any warning has been given."""
        self._warned = False

    def deliverable(self, lessons: Sequence[Lesson]) -> list[Lesson]:
        """`lessons` without those an older mining kept; warns once when any was dropped."""
        kept = taught_since_the_fix_rule(lessons)
        if len(kept) < len(lessons) and not self._warned:
            self._warned = True
            log.warning(
                "this store was mined before the known-fix rule; %d stored lessons are not "
                "delivered. Run `symbiont repo mine` to refresh it.",
                len(lessons) - len(kept),
            )
        return kept
