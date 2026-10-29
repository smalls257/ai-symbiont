"""The lesson author: Muse Spark writes a child card, and a reply that is not a card raises.

Nothing guesses a child. The reply is parsed line by line in a fixed form; any other line raises
`MutationReplyError`, and a card over the caps raises `CardCapError` from the genome. Every call
goes through `SparkSession.chat`, which checks the cap and the privacy of the payload and records
the spend under the label `evolve/<run>/author/<parent>`. The API takes no seed, so the `seed`
argument is unused: a rerun is protected by the generation journal, not by the model.
"""

from dataclasses import dataclass

import prompts

from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.generation import MutationReplyError
from symbiont.act1.lineage import Operator
from symbiont.egress.spark import Effort, SparkSession

AUTHOR_NAME = "spark-muse"
# Medium reasoning once spent all 4096 default tokens thinking and left no answer (measured on the
# first evolution run), so mutation calls get room for the thinking and the answer.
REPLY_TOKENS = 16384


def parse_card(text: str) -> Card:
    """The reply as a card. Raises MutationReplyError, or CardCapError over the caps."""
    stripped = text.strip()
    if stripped == prompts.EMPTY_CARD_REPLY:
        return Card.of([])
    lessons = []
    for number, line in enumerate(stripped.splitlines(), 1):
        if not line.strip():
            continue
        if not line.startswith(prompts.LESSON_PREFIX):
            raise MutationReplyError(f"line {number} of the reply is not a lesson line")
        parts = [
            p.strip() for p in line.removeprefix(prompts.LESSON_PREFIX).split(prompts.SEPARATOR)
        ]
        if len(parts) != 3 or not all(parts):
            raise MutationReplyError(f"line {number} does not have three non-empty parts")
        lessons.append(Lesson(*parts))
    if not lessons:
        raise MutationReplyError("the reply holds no lesson and is not the empty-card reply")
    return Card.of(lessons)


@dataclass(frozen=True)
class SparkAuthor:
    """Implements the loop's Author protocol over a Spark session."""

    session: SparkSession
    effort: Effort
    name: str = AUTHOR_NAME

    def vary(self, operator: Operator, parents: tuple[Card, ...], summary: str, seed: int) -> Card:
        """A child of the first parent. Raises MutationReplyError, CardCapError or a Spark error."""
        parent = parents[0]
        label = f"evolve/{self.session.run}/author/{parent.card_id}"
        prompt = prompts.author_prompt(operator, parent, summary)
        return parse_card(self.session.chat(prompt, self.effort, label, REPLY_TOKENS).text)
