"""What the developer said about a lesson, in their own words."""

from dataclasses import dataclass
from enum import StrEnum


class Priority(StrEnum):
    """How much the developer cares that this lesson is heard."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True)
class LessonContext:
    """The developer's words for a lesson; `intentional` says the failure is on purpose."""

    text: str
    intentional: bool = False
    priority: Priority = Priority.NORMAL
