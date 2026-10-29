"""Spark players that may see one situational lesson per decision, only above a ranker cutoff.

Picklable like spark_players: a worker rebuilds the ranker from the lessons file. Every decision
appends a line (level, seed, decision, how many lessons were shown, the top score) to the shows
file, so the show rate is measured, not assumed. The lesson block goes just before "Now:".
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import spark_players

from symbiont.act1.card_genome import Card
from symbiont.act1.game_fitness import Case
from symbiont.act1.glimmer import Reply, ReplyFn
from symbiont.act1.situational import Ranker, SituationalLesson, render_lessons
from symbiont.egress.spark import DEFAULT_MAX_TOKENS, Effort

NOW = "\n\nNow: "


class Delivery(StrEnum):
    """What the arm does when the ranker would fire: put the lesson in the prompt, or only note it.

    NOTHING exists so every arm of a paired test measures "would fire" with the same rule on its
    own observations; the no-lesson arm computes it and shows nothing.
    """

    ADVICE = "advice"
    NOTHING = "nothing"


@lru_cache(maxsize=2)
def ranker_from(path: str, leave_out: str = "") -> Ranker:
    """The ranker over a lessons file; lessons mined from levels named `leave_out` are left out."""
    items = json.loads(Path(path).read_text())["lessons"]
    return Ranker(
        [
            SituationalLesson(i["advice"], tuple(i["examples"]))
            for i in items
            if not (leave_out and i["source"].startswith(leave_out))
        ]
    )


@dataclass(frozen=True)
class LessonPlayers:
    """Muse Spark at low effort, shown at most two lessons when the top score reaches the cutoff."""

    run: str
    run_cap: float
    lessons: str
    cutoff: float
    shows: str
    delivery: Delivery = Delivery.ADVICE

    def __call__(self, card: Card, case: Case) -> ReplyFn:
        """The reply function of one game."""
        base = spark_players.SparkPlayers(
            run=self.run, run_cap=self.run_cap, effort=Effort.LOW, max_tokens=DEFAULT_MAX_TOKENS
        )(card, case)
        ranker = ranker_from(self.lessons)
        decision = [0]

        def reply(prompt: str) -> Reply:
            head, _, observation = prompt.rpartition(NOW)
            advice = ranker.choose(observation, self.cutoff)
            self._record(case, decision[0], len(advice), max(ranker.scores(observation)))
            decision[0] += 1
            block = render_lessons(advice) if self.delivery == Delivery.ADVICE else ""
            return base(head + (f"\n\n{block}" if block else "") + NOW + observation)

        return reply

    def _record(self, case: Case, decision: int, shown: int, top: float) -> None:
        """One line per decision: the show rate is read from these."""
        line = {"level": case.level, "seed": case.seed, "decision": decision, "shown": shown,
                "top": round(top, 4)}  # fmt: skip
        with Path(self.shows).open("a", encoding="utf-8") as out:
            out.write(json.dumps(line) + "\n")
