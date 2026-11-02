"""The agree rule's recall: a stored note is shown only if the ranker and the judge agree."""

from typing import TYPE_CHECKING

from symbiont.core.agree import AGREE, NIGHTLY, Verdict, agree
from symbiont.core.judge_format import fix_commands
from symbiont.miner.lessons import Lesson
from symbiont.miner.twins import merge_twins
from symbiont.service.events import Call
from symbiont.service.follow_up import FollowUp, ShownNote
from symbiont.service.judge_model import JudgeOfflineError

if TYPE_CHECKING:
    from symbiont.service.app import ServiceParts

NOTHING_MATCHES = "nothing in this project's history matches that question"


class AgreedRecall:
    """Answers a question from the first-night or nightly judge; a down judge raises."""

    def __init__(self, parts: "ServiceParts", follow_up: FollowUp) -> None:
        """Keep the service parts (judges, events) and the follow-up that watches shown notes."""
        self._parts = parts
        self._follow_up = follow_up

    def answer(
        self, call: Call, project: str, question: str, lessons: list[Lesson]
    ) -> tuple[str, list[Lesson]]:
        """The stored note and its lesson, or NOTHING_MATCHES; a down judge raises (503)."""
        merged = merge_twins(lessons)
        nightly = self._parts.nightly.judge_for(project, merged) if self._parts.nightly else None
        judge, bars = (nightly, NIGHTLY) if nightly else (self._parts.judge, AGREE)
        rule = "nightly" if nightly else "agree"
        if judge is None:
            raise JudgeOfflineError("no first-night judge is configured (--judge-url)")
        outcome = agree(question, project, merged, judge.p_yes, bars)
        if outcome.verdict is Verdict.AGREED and outcome.lesson and outcome.note:
            refs = outcome.lesson.pain_point.record_refs
            note_id = ":".join(map(str, refs[0])) if refs else outcome.lesson.pain_point.session_id
            fixes = fix_commands(outcome.lesson)
            self._follow_up.shown(call, project, ShownNote(note_id, rule, fixes))
            return outcome.note, [outcome.lesson]
        numbers = {
            "ranker_score": outcome.ranker_score,
            "ranker_cut": outcome.ranker_cut,
            "ceiling": outcome.ceiling,
            "judge_p_yes": outcome.judge_p_yes,
        }
        self._parts.events.append_note_held(call, f"{rule}:{outcome.verdict.value}", numbers)
        return NOTHING_MATCHES, []
