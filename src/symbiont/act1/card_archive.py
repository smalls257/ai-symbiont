"""Niche archive: the best card per (length, focus) across generations (pure).

It is a record of which strategies survived, not a source of candidates (plan ruling 7): picking
uses the stated rule over the cards that played, so the archive cannot change who is picked.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from symbiont.act1.card_genome import Card, Lesson

SHORT_MAX_LESSONS = 4  # design section 4: up to 4 lessons is short, 5 to 8 is long


class Length(StrEnum):
    """Card length niche."""

    SHORT = "up to 4 lessons"
    LONG = "5 to 8"


class Focus(StrEnum):
    """What a card mostly talks about."""

    NAVIGATION = "navigation"
    COMBAT = "combat"


# The builder's call (the design leaves niche boundaries open): plain words a lesson uses when it
# is about fighting or about getting through the level.
COMBAT_WORDS = frozenset(
    {
        "shoot",
        "shooting",
        "shot",
        "shots",
        "fire",
        "fired",
        "firing",
        "enemy",
        "enemies",
        "monster",
        "monsters",
        "ammo",
        "ammunition",
        "weapon",
        "attack",
        "attacked",
        "kill",
        "killed",
        "fight",
        "health",
        "hurt",
        "damage",
        "aim",
        "aimed",
    }
)
NAVIGATION_WORDS = frozenset(
    {
        "door",
        "doors",
        "exit",
        "key",
        "keys",
        "room",
        "rooms",
        "wall",
        "walls",
        "walk",
        "walked",
        "route",
        "path",
        "corridor",
        "locked",
        "turn",
        "turned",
        "switch",
        "stuck",
        "explore",
        "level",
        "go_to",
        "open",
    }
)


def _is_combat(lesson: Lesson) -> bool:
    """More combat words than navigation words in the lesson's three parts."""
    words = re.findall(r"[a-z_]+", f"{lesson.went_wrong} {lesson.instead} {lesson.check}".lower())
    combat = sum(word in COMBAT_WORDS for word in words)
    return combat > sum(word in NAVIGATION_WORDS for word in words)


def focus_of(card: Card) -> Focus:
    """Combat when more than half the lessons are combat lessons; the empty card is navigation."""
    combat = sum(_is_combat(lesson) for lesson in card.lessons)
    return Focus.COMBAT if 2 * combat > len(card.lessons) else Focus.NAVIGATION


def niche_of(card: Card) -> tuple[Length, Focus]:
    """The (length, focus) cell a card belongs to."""
    length = Length.SHORT if len(card.lessons) <= SHORT_MAX_LESSONS else Length.LONG
    return length, focus_of(card)


@dataclass
class Archive:
    """Best (card id, mean fitness) per niche; a tie goes to the shorter card."""

    best: dict[tuple[Length, Focus], tuple[str, float]] = field(default_factory=dict)
    _tie_keys: dict[tuple[Length, Focus], tuple[int, str]] = field(default_factory=dict, repr=False)

    def offer(self, card: Card, mean_fitness: float) -> bool:
        """Keep the card if it beats its niche's holder (or ties it and is shorter)."""
        niche = niche_of(card)
        held = self.best.get(niche)
        if held is not None:
            held_key = (-held[1], self._tie_keys[niche])
            if held_key <= (-mean_fitness, card.tie_key()):
                return False
        self.best[niche] = (card.card_id, mean_fitness)
        self._tie_keys[niche] = card.tie_key()
        return True

    def to_json(self) -> dict[str, Any]:
        """Ids and numbers only; a lesson's text never leaves the run state."""
        cells = [
            {"length": length.name, "focus": focus.value, "card_id": card_id, "mean_fitness": mean}
            for (length, focus), (card_id, mean) in sorted(self.best.items())
        ]
        return {"niches": cells}
