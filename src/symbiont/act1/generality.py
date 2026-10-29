"""The generality filter: a lesson that names a place cannot help on a level never seen (pure).

A card that memorizes "the third door on MAP07" wins training and teaches nothing. These named
patterns catch the literal cases; the second judge call (a later task) catches landmark prose.
A rejection always carries its reason and the matched text, so the generation log shows what was
turned away and why.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.env_text import ENEMY_NAMES


class Rejection(StrEnum):
    """Why a lesson was turned away. LANDMARK is set only by the judge, never by a pattern here."""

    MAP_NAME = "map_name"
    COORDINATE = "coordinate"
    SECTOR = "sector"
    DOOR_NUMBER = "door_number"
    MONSTER_POSITION = "monster_position"
    LANDMARK = "landmark"


@dataclass(frozen=True)
class Verdict:
    """Whether a lesson is general; `evidence` is the matched text of a rejection."""

    general: bool
    rejection: Rejection | None
    evidence: str


_ORDINALS = r"(?:\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth)"
_MONSTER_WORDS = sorted(
    {name.lower() for name in ENEMY_NAMES} | {"imp", "zombie", "zombieman", "demon"}, key=len
)
_PLACE_WORDS = r"(?:by|behind|at|near|beside|next to|in front of|on top of|under)\s+the"
_MONSTER = rf"\b(?:{'|'.join(reversed(_MONSTER_WORDS))})s?\s+{_PLACE_WORDS}\b"

# Checked in this order; the first match names the rejection.
PATTERNS: tuple[tuple[Rejection, re.Pattern[str]], ...] = (
    (Rejection.MAP_NAME, re.compile(r"\bMAP\d{2}\b|\bE\dM\d\b", re.IGNORECASE)),
    (
        Rejection.COORDINATE,
        re.compile(
            r"\b[xy]\s*=\s*-?\d+"
            r"|\(\s*-?\d+\s*,\s*-?\d+\s*\)"
            r"|\bat\s+-?\d+\s*,\s*-?\d+"
            r"|-?\d{3,}\s*,\s*-?\d{3,}",
            re.IGNORECASE,
        ),
    ),
    (Rejection.SECTOR, re.compile(r"\bsector\s+\d+", re.IGNORECASE)),
    (
        Rejection.DOOR_NUMBER,
        re.compile(rf"\bdoor\s+(?:number\s+)?\d+|\bthe\s+{_ORDINALS}\s+door\b", re.IGNORECASE),
    ),
    (Rejection.MONSTER_POSITION, re.compile(_MONSTER, re.IGNORECASE)),
)


def check_lesson(lesson: Lesson) -> Verdict:
    """The first named pattern the lesson's three parts match, or a general verdict."""
    text = f"{lesson.went_wrong}\n{lesson.instead}\n{lesson.check}"
    for rejection, pattern in PATTERNS:
        found = pattern.search(text)
        if found:
            return Verdict(general=False, rejection=rejection, evidence=found.group(0))
    return Verdict(general=True, rejection=None, evidence="")


def check_text(text: str) -> Verdict:
    """The same scan over free text, for summaries shown to an author."""
    return check_lesson(Lesson(text, text, text))


def check_card(card: Card) -> tuple[Verdict, ...]:
    """One verdict per lesson, in card order."""
    return tuple(check_lesson(lesson) for lesson in card.lessons)
