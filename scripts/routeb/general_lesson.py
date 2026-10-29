"""One general lesson: what happened, how it was resolved and the check to run, with its counts.

A general lesson names no evaluation task and no single fix; its support says how many runs or
upstream fixes show it, and which non-evaluation tasks those came from. Pure.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class LessonKind(StrEnum):
    """What a general lesson teaches."""

    HABIT = "habit"  # a process habit from Glimmer's own runs
    REPO = "repo-knowledge"  # where kinds of fixes live in sqlglot, and its tests
    IMPLEMENTATION = "implementation"  # how new capability is added, from feature tasks


@dataclass(frozen=True)
class GeneralLesson:
    """A three-part lesson with the counts that support it."""

    lesson_id: str
    kind: LessonKind
    situation: str  # second person, present tense: when this lesson applies
    happened: str
    resolved: str
    check: str
    support: dict[str, int] = field(default_factory=dict)
    source_tasks: tuple[str, ...] = ()
    teaches: tuple[str, ...] = ()  # place kinds the lesson names, for the pattern-close report

    def card(self) -> str:
        """The lesson in the three-part form."""
        return (
            f"What happened: {self.happened} How it was resolved: {self.resolved} "
            f"The check to run: {self.check}"
        )


def share(part: int, whole: int) -> str:
    """'7 of 20' as prose."""
    return f"{part} of {whole}"
