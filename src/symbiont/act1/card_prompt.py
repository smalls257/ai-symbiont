"""How a card reaches the player: as prose placed before the game prompt (pure).

The empty card returns the reply function untouched, so the no-card arm's prompt is byte-identical
to a game played without Evolve. No score, id or flag is added: the player reads lessons, nothing
about how they were chosen.
"""

from enum import StrEnum

from symbiont.act1.card_genome import Card
from symbiont.act1.glimmer import Reply, ReplyFn

LESSONS_HEADING = "Lessons from earlier games:"
RULES_HEADING = "Rules you must follow:"


class CardPlacement(StrEnum):
    """Where a card is shown: in front of the game prompt, or as rules in a system message."""

    PROMPT_PREFIX = "prompt_prefix"
    SYSTEM_RULES = "system_rules"


def system_rules(card: Card) -> str | None:
    """The card as a system message, or None for the empty card (no message at all)."""
    if not card.lessons:
        return None
    return f"{RULES_HEADING}\n{card.render()}"


def with_card(reply_fn: ReplyFn, card: Card) -> ReplyFn:
    """A reply function that puts the card's lessons before every prompt it is asked."""
    if not card.lessons:
        return reply_fn
    prefix = f"{LESSONS_HEADING}\n{card.render()}\n\n"

    def reply_with_lessons(prompt: str) -> Reply:
        """Ask the wrapped function with the lessons in front."""
        return reply_fn(prefix + prompt)

    return reply_with_lessons
