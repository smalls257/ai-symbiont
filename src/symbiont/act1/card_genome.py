"""The lesson card: the genome Evolve varies (pure).

A card is a few lessons in the three-part form (what went wrong, what to do instead, the check to
make), shown to a player as prose and never as a score. An oversized or malformed card raises:
truncating it quietly would let a mutation smuggle in text the selection never saw.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

# Design section 4 (docs/design/2026-10-28-evolve.md): a card holds at most 8 lessons and 250 words.
MAX_LESSONS = 8
MAX_WORDS = 250
_ID_HEX_DIGITS = 12


class CardCapError(ValueError):
    """A card with more lessons or words than the design allows."""


class LessonFormError(ValueError):
    """A lesson with an empty part: the three-part form is the contract."""


@dataclass(frozen=True)
class Lesson:
    """One lesson; `source_level` names the training level it came from (None: history)."""

    went_wrong: str
    instead: str
    check: str
    source_level: str | None = None

    def __post_init__(self) -> None:
        """Refuse an empty part, naming it."""
        for part, text in (
            ("went_wrong", self.went_wrong),
            ("instead", self.instead),
            ("check", self.check),
        ):
            if not text.strip():
                raise LessonFormError(f"lesson part {part!r} is empty")

    def to_json(self) -> dict[str, str | None]:
        """The lesson as plain JSON (for the run's own state file, never for publishing)."""
        return {
            "went_wrong": self.went_wrong,
            "instead": self.instead,
            "check": self.check,
            "source_level": self.source_level,
        }

    @classmethod
    def from_json(cls, data: dict[str, str | None]) -> "Lesson":
        """The inverse of to_json; raises LessonFormError for an empty part."""
        return cls(
            str(data["went_wrong"]), str(data["instead"]), str(data["check"]), data["source_level"]
        )

    def words(self) -> int:
        """Words over the three parts."""
        return sum(len(part.split()) for part in (self.went_wrong, self.instead, self.check))

    def render(self) -> str:
        """The lesson as one prose line, without its number."""
        parts = (self.went_wrong, self.instead, self.check)
        went_wrong, instead, check = (part.strip().rstrip(".") for part in parts)
        return f"What went wrong: {went_wrong}. Instead: {instead}. Check: {check}."


@dataclass(frozen=True)
class Card:
    """An ordered set of lessons within the caps. Build with `Card.of`."""

    lessons: tuple[Lesson, ...]

    def __post_init__(self) -> None:
        """Enforce both caps for every construction path."""
        if len(self.lessons) > MAX_LESSONS:
            raise CardCapError(f"{len(self.lessons)} lessons; the cap is {MAX_LESSONS}")
        if self.words() > MAX_WORDS:
            raise CardCapError(f"{self.words()} words; the cap is {MAX_WORDS}")

    @classmethod
    def of(cls, lessons: Sequence[Lesson]) -> "Card":
        """A card from lessons; raises CardCapError when over a cap."""
        return cls(tuple(lessons))

    def to_json(self) -> list[dict[str, str | None]]:
        """The card as plain JSON."""
        return [lesson.to_json() for lesson in self.lessons]

    @classmethod
    def from_json(cls, data: list[dict[str, str | None]]) -> "Card":
        """The inverse of to_json; raises CardCapError or LessonFormError for a bad card."""
        return cls.of([Lesson.from_json(item) for item in data])

    def words(self) -> int:
        """Words over every lesson."""
        return sum(lesson.words() for lesson in self.lessons)

    def render(self) -> str:
        """Numbered lines; the empty card renders to the empty string."""
        return "\n".join(f"{n}. {lesson.render()}" for n, lesson in enumerate(self.lessons, 1))

    @property
    def card_id(self) -> str:
        """Twelve hex digits of the rendered text's sha256: equal text, equal id."""
        return hashlib.sha256(self.render().encode()).hexdigest()[:_ID_HEX_DIGITS]

    def tie_key(self) -> tuple[int, str]:
        """Sort key for ties: fewer words first, then id. Shorter cards win."""
        return (self.words(), self.card_id)
