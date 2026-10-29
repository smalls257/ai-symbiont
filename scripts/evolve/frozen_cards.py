"""The two cards of the scored card test, their hashes and the held-out cases, in one place.

The prereg quotes both cards' exact text and the sha256 of that text (`Card.render()` with no
trailing newline). `final_test.py check` recomputes the hashes from these definitions and refuses
on a mismatch, so a card cannot change after the freeze without the check saying so.
"""

import hashlib

from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.game_fitness import Case
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting

# The best of the six generation-0 cards: the miner's own check texts for the two most common
# mistakes of Glimmer's starting point (moves that changed nothing, rooms checked again).
MINED_CARD = Card.of(
    [
        Lesson(
            "Moves that changed nothing",
            "Pick a move that goes somewhere or changes something",
            "Turn toward a side the Layout line calls open; a turn that ends facing the same way "
            "wastes a decision.",
        ),
        Lesson(
            "Turning in a room already scanned",
            "Head for an exit, door or key instead",
            "Do not turn to look around a room you already scanned; pick a door, key or exit "
            "from 'Reachable with go_to' instead.",
        ),
    ]
)
STRONG_CARD = Card.of(
    [
        Lesson(
            "Wandering without a target",
            "Go to the nearest unexplored door with go_to(door) and open it",
            "Does 'Reachable with go_to' list a door you have not used yet?",
        ),
        Lesson(
            "Walking back into rooms already checked",
            "Never re-enter a room you already checked; pick a door you have not used",
            "Have you been in this room before?",
        ),
        Lesson(
            "Missing the exit",
            "When an exit sign is in view or listed, head for it with go_to(exit) at once",
            "Does the observation list an exit?",
        ),
    ]
)
NO_CARD = Card.of([])
ARMS = {"none": NO_CARD, "mined": MINED_CARD, "strong": STRONG_CARD}
HELD_OUT_MAPS = ("MAP04", "MAP08", "MAP12", "MAP16", "MAP24", "MAP28", "MAP32")
SEEDS = tuple(range(2001, 2015))  # fourteen seeds on each of the seven maps: 98 cases


def card_sha256(card: Card) -> str:
    """sha256 of the card's rendered text exactly as the player receives it (no newline)."""
    return hashlib.sha256(card.render().encode()).hexdigest()


def scored_cases() -> tuple[Case, ...]:
    """The 98 cases, one seed at a time across all seven maps; normal skill, no cut moves."""
    return tuple(
        Case(level, seed, NORMAL_SKILL, CutSetting.NONE)
        for seed in SEEDS
        for level in HELD_OUT_MAPS
    )
