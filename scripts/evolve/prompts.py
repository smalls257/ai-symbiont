"""The words Evolve says to Muse Spark when it writes and judges lessons.

The prompts hold prose and card text only: no score, no map name, no coordinate. The reply formats
are fixed so a parser can refuse anything else.
"""

from symbiont.act1.card_genome import Card
from symbiont.act1.lineage import Operator

LESSON_PREFIX = "LESSON:"
SEPARATOR = "||"
EMPTY_CARD_REPLY = "EMPTY CARD"
GENERAL_REPLY = "GENERAL"
LANDMARK_PREFIX = "LANDMARK:"

OPERATOR_TASKS = {
    Operator.REWRITE: "Rewrite one lesson of the card so it is clearer or applies more widely.",
    Operator.ADD: "Add one new lesson for a mistake the games summary describes.",
    Operator.DELETE: "Remove the one lesson that looks least useful.",
    Operator.MERGE: "Merge two lessons of the card that say nearly the same thing into one.",
    Operator.SEED_SPARK: (
        "Write a first card of 3 to 5 lessons for the mistakes the summary describes."
    ),
}
FORMAT_RULES = (
    f"Reply with the complete new card, one lesson per line, exactly in this form:\n"
    f"{LESSON_PREFIX} <what went wrong> {SEPARATOR} <what to do instead> {SEPARATOR} "
    f"<the check to make>\n"
    f"If the card ends up with no lessons, reply exactly: {EMPTY_CARD_REPLY}\n"
    "Rules: at most 8 lessons and 250 words in all. A lesson must hold on any level of the game: "
    "never name a map, a coordinate, a sector, a door by number or position, or a landmark such "
    "as 'the room with the blue key'. Say nothing else."
)


def author_prompt(operator: Operator, parent: Card, summary: str) -> str:
    """The mutation prompt: the task, the parent card, what happened in its games, the format."""
    card_text = parent.render() or "(the card has no lessons yet)"
    return (
        "You improve a short card of lessons that a model reads before it plays a Freedoom "
        "level through text descriptions.\n\n"
        f"Task: {OPERATOR_TASKS[operator]}\n\n"
        f"The card now:\n{card_text}\n\n"
        f"What happened in games played with this card: {summary}\n\n{FORMAT_RULES}"
    )


def judge_prompt(lesson_text: str) -> str:
    """The landmark judge prompt for one rendered lesson."""
    return (
        "A lesson is meant to help a model on ANY level of a game. Decide whether this lesson "
        "points at a particular place (a landmark, a room described by what it holds, a position "
        "such as 'second on the left') instead of a habit that works everywhere.\n\n"
        f"Lesson: {lesson_text}\n\n"
        f"Reply exactly {GENERAL_REPLY} or {LANDMARK_PREFIX} <short reason>. Nothing else."
    )
