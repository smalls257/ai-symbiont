"""The landmark judge: Muse Spark says whether a lesson points at a place instead of a habit.

The reply is `GENERAL` or `LANDMARK: <reason>`; anything else raises `JudgeReplyError`, so a
lesson is never waved through on a reply nobody understood. Spend is recorded under the label
`evolve/<run>/judge`.
"""

from dataclasses import dataclass

import prompts

from symbiont.act1.card_genome import Lesson
from symbiont.act1.generality import Rejection, Verdict
from symbiont.egress.spark import Effort, SparkSession

MAX_REASON_CHARS = 200


class JudgeReplyError(ValueError):
    """The judge's reply was neither GENERAL nor LANDMARK with a reason."""


def parse_verdict(text: str) -> Verdict:
    """The reply as a verdict. Raises JudgeReplyError."""
    reply = text.strip()
    if reply == prompts.GENERAL_REPLY:
        return Verdict(general=True, rejection=None, evidence="")
    if reply.startswith(prompts.LANDMARK_PREFIX):
        reason = reply.removeprefix(prompts.LANDMARK_PREFIX).strip()[:MAX_REASON_CHARS]
        if reason:
            return Verdict(general=False, rejection=Rejection.LANDMARK, evidence=reason)
    raise JudgeReplyError("the reply is neither GENERAL nor LANDMARK with a reason")


@dataclass(frozen=True)
class SparkJudge:
    """Implements the loop's Judge protocol over a Spark session."""

    session: SparkSession
    effort: Effort

    def landmark(self, lesson: Lesson) -> Verdict:
        """The judge's verdict on one lesson. Raises JudgeReplyError or a Spark error."""
        label = f"evolve/{self.session.run}/judge"
        prompt = prompts.judge_prompt(lesson.render())
        return parse_verdict(self.session.chat(prompt, self.effort, label).text)
