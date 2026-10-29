"""A player that scores by a hidden rule and plays no game: for dry runs of the whole loop.

Cards whose lessons talk about doors do a little better, more on some levels. It exists to prove
the loop (selection, guards, resume, page) runs end to end before any model or engine is used.
"""

import hashlib

from symbiont.act1.card_genome import Card
from symbiont.act1.game_fitness import Case, GameResult, Grade

DOOR_EFFECT = 0.06  # route share gained per door lesson (a dry-run setting, not a measurement)
LUCK = 0.02  # size of the per-case luck every card shares


def door_lessons(card: Card) -> int:
    """How many lessons talk about doors."""
    return sum("door" in f"{lesson.went_wrong} {lesson.instead}".lower() for lesson in card.lessons)


class HiddenRulePlayer:
    """Implements the loop's Player protocol without an engine."""

    def play(self, card: Card, case: Case) -> GameResult:
        """A graded game whose route share follows the hidden rule plus shared luck."""
        strength = 1 + (int(case.level[3:]) % 3) / 3
        digest = hashlib.sha256(str(case).encode()).digest()[0]
        luck = LUCK * (digest / 127.5 - 1)
        share = min(max(0.5 + DOOR_EFFECT * door_lessons(card) * strength + luck, 0.0), 1.0)
        return GameResult(
            case=case,
            card_id=card.card_id,
            grade=Grade.GRADED,
            exit_reached=False,
            route_share=share,
            mistakes=0,
            died=False,
            kills=0,
            cut_moves=0,
            ungraded_reason=None,
        )
