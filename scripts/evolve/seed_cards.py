"""Generation 0 cards: the empty card, two built from the tagger's own checks, three from Spark.

History lessons are not read here: the four Glimmer history games are not in this checkout, so the
two built cards take the tagger's own check texts, ordered by how often the design's measured
starting point saw each mistake (26 wasted moves, 9 rooms re-checked, 5 wall bumps, 4 rooms
re-entered). Every card must pass the pattern filter and the judge or the build raises: a seed card
is never quietly replaced.
"""

from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.game_lessons import (
    RECHECKED_CHECK,
    REENTERED_CHECK,
    WALL_CHECKS,
    WASTED_CHECKS,
)
from symbiont.act1.generality import Verdict, check_lesson
from symbiont.act1.generation import Author, Judge
from symbiont.act1.lineage import Operator

# Plain Glimmer's measured starting point (design section 1) in prose, counts only, no map names.
START_SUMMARY = (
    "In 4 games by a plain model the exit was not reached in any. Of 44 tagged mistakes, 26 were "
    "moves that changed nothing, 9 were turns in rooms already checked, 5 were walks into walls "
    "and 4 were returns to rooms already left. It fought well: 17 kills and no deaths."
)
SEED_FOCUSES = (
    "Focus on getting through the level.",
    "Focus on not wasting moves.",
    "Cover both getting through the level and not wasting moves.",
)
PAIN_LESSONS = (
    Lesson(
        "Moves that changed nothing",
        "Pick a move that goes somewhere or changes something",
        WASTED_CHECKS[-1][2],
    ),
    Lesson(
        "Turning in a room already scanned",
        "Head for an exit, door or key instead",
        RECHECKED_CHECK,
    ),
    Lesson("Walking into a wall", "Use go_to so the route goes around walls", WALL_CHECKS[0][2]),
    Lesson(
        "Going back into a room already left", "Take a route you have not used", REENTERED_CHECK
    ),
)
TOP_TWO = 2


class GeneralityRejectedError(ValueError):
    """A seed card was turned away by the pattern filter or the judge."""


def built_cards() -> tuple[Card, Card]:
    """Card A: the two most common mistakes. Card B: one lesson per mistake kind."""
    return Card.of(PAIN_LESSONS[:TOP_TWO]), Card.of(PAIN_LESSONS)


def _require_general(card: Card, judge: Judge) -> None:
    """Raises GeneralityRejectedError naming the first lesson turned away."""
    for lesson in card.lessons:
        verdict: Verdict = check_lesson(lesson)
        if verdict.general:
            verdict = judge.landmark(lesson)
        if not verdict.general:
            raise GeneralityRejectedError(f"{card.card_id}: {verdict.rejection} {verdict.evidence}")


def build_seed_cards(author: Author, judge: Judge) -> list[Card]:
    """Six distinct generation-0 cards. Raises GeneralityRejectedError or a reply error."""
    empty = Card.of([])
    cards = [empty, *built_cards()]
    for seed, focus in enumerate(SEED_FOCUSES):
        cards.append(author.vary(Operator.SEED_SPARK, (empty,), f"{START_SUMMARY} {focus}", seed))
    for card in cards:
        _require_general(card, judge)
    if len({card.card_id for card in cards}) != len(cards):
        raise GeneralityRejectedError("two seed cards are identical")
    return cards
