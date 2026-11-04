"""The agree rule's recall: a stored note is shown only if the ranker and the judge agree.

A repository with a trained checker never gets the ranker's note alone: a checker that is down
answers "symbiont checker offline" (503), and the service starts it again once, loudly, from the
facts in the nightly record.
"""

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from symbiont.core.agree import AGREE, NIGHTLY, Verdict, agree
from symbiont.core.judge_format import (
    failure_situation,
    fix_commands,
    judge_input,
    judgeable,
)
from symbiont.core.repeat import REPEAT_WHY
from symbiont.miner.lessons import Lesson
from symbiont.miner.twins import merge_twins
from symbiont.records.schema import Record
from symbiont.service.events import Call
from symbiont.service.follow_up import FollowUp, ShownNote
from symbiont.service.judge_model import JudgeModel, JudgeOfflineError, JudgeSlowError
from symbiont.service.judge_start import JudgeStartError, Running
from symbiont.service.nightly import NightlyState
from symbiont.service.repo_gate import Spoken

if TYPE_CHECKING:
    from symbiont.service.app import ServiceParts

log = logging.getLogger(__name__)
NOTHING_MATCHES = "nothing in this project's history matches that question"
CHECKER = "Llama 3.2 1B"
# A hook has 0.6 s end to end (delivery/launch.HOOK_TIMEOUT_S) and a warm score takes ~0.1-0.2 s;
# the rest is the service round trip. Slower than this, the note is dropped with a visible line.
HOOK_BUDGET_S = 0.35
JUDGE_LOG = "judge-server.log"


@dataclass(frozen=True)
class CheckerVerdict:
    """Which checker agreed to a shown note: what `symbiont why` and the dashboard say about it."""

    rule: str
    lessons: int | None
    trained_at: str | None

    def as_event(self) -> dict[str, object]:
        """The event-log fields: verdict and what the checker was trained on, never a score."""
        return {
            "checker": CHECKER,
            "rule": self.rule,
            "verdict": "agreed",
            "lessons": self.lessons,
            "trained_at": self.trained_at,
        }


@dataclass(frozen=True)
class AgreedAnswer:
    """The recall answer, the lessons it cites and, for a shown note, the checker that agreed."""

    text: str
    lessons: list[Lesson]
    checked_by: CheckerVerdict | None = None


class AgreedRecall:
    """Answers a question from the first-night or nightly judge; a down judge raises."""

    def __init__(self, parts: "ServiceParts", follow_up: FollowUp) -> None:
        """Keep the service parts (judges, events) and the follow-up that watches shown notes."""
        self._parts = parts
        self._follow_up = follow_up
        self._started: dict[str, Running] = {}

    def applies(self, project: str) -> bool:
        """Whether the agree rule must answer for `project`: a configured judge or a trained one."""
        nightly = self._parts.nightly
        return self._parts.judge is not None or (
            nightly is not None and nightly.has_record(project)
        )

    def answer(
        self, call: Call, project: str, question: str, lessons: list[Lesson]
    ) -> AgreedAnswer:
        """The stored note and its lesson, or NOTHING_MATCHES; a down judge raises (503)."""
        merged = merge_twins(lessons)
        nightly = self._parts.nightly.judge_for(project, merged) if self._parts.nightly else None
        judge, bars = (nightly, NIGHTLY) if nightly else (self._parts.judge, AGREE)
        rule = "nightly" if nightly else "agree"
        if judge is None:
            raise JudgeOfflineError("no first-night judge is configured (--judge-url)")
        try:
            outcome = agree(question, project, merged, judge.p_yes, bars)
        except JudgeOfflineError as down:
            if nightly is None:
                raise
            raise self._down(project, down) from down
        if outcome.verdict is Verdict.AGREED and outcome.lesson and outcome.note:
            refs = outcome.lesson.pain_point.record_refs
            note_id = ":".join(map(str, refs[0])) if refs else outcome.lesson.pain_point.session_id
            fixes = fix_commands(outcome.lesson)
            self._follow_up.shown(call, project, ShownNote(note_id, rule, fixes))
            return AgreedAnswer(
                outcome.note, [outcome.lesson], self._verdict(project, rule, merged)
            )
        numbers = {
            "ranker_score": outcome.ranker_score,
            "ranker_cut": outcome.ranker_cut,
            "ceiling": outcome.ceiling,
            "judge_p_yes": outcome.judge_p_yes,
        }
        self._parts.events.append_note_held(call, f"{rule}:{outcome.verdict.value}", numbers)
        return AgreedAnswer(NOTHING_MATCHES, [])

    def _verdict(self, project: str, rule: str, lessons: list[Lesson]) -> CheckerVerdict:
        """Which checker agreed: the nightly one with its training, else the first-night one."""
        nightly = self._parts.nightly
        if rule != "nightly" or nightly is None:
            return CheckerVerdict(rule, None, None)
        report = nightly.report(project, lessons)
        trained = report.state in (NightlyState.TRAINED, NightlyState.STALE)
        return CheckerVerdict(rule, report.lessons if trained else None, report.trained_at)

    def vet(
        self, call: Call, record: Record, said: Spoken, lessons: list[Lesson]
    ) -> tuple[Spoken, CheckerVerdict | None]:
        """Let the trained checker gate a hook-time failure recall; rule notes pass as is.

        A no silences the note and logs why. A down or slow checker raises (503) and the
        once-per-session mark is withdrawn, so the next repeat is checked again.
        """
        found, nightly, project = said.note, self._parts.nightly, record.project
        if found is None or found.lesson is None or found.why != REPEAT_WHY:
            return said, None
        if nightly is None or not nightly.has_record(project):
            return said, None
        try:
            judge = nightly.judge_for(project, merge_twins(lessons))
            if judge is None:
                return said, None
            agreed = self._judged(call, judge, record, found.lesson)
        except JudgeOfflineError as down:
            self._parts.gate.forget_said(said.once)
            raise self._down(project, down) from down
        if not agreed:
            return replace(said, notes=()), None
        return said, self._verdict(project, "nightly", lessons)

    def _judged(self, call: Call, judge: JudgeModel, record: Record, lesson: Lesson) -> bool:
        """Whether the judge agrees the stored lesson applies to this failure.

        A no is logged as a held note with the reason (never the text).
        """
        situation = failure_situation(record, record.project)
        pair = judgeable(lesson, record.project)
        if situation is None or pair is None:
            self._parts.events.append_note_held(call, "nightly:not_judgeable", {})
            return False
        slim = replace(judge, timeout_s=HOOK_BUDGET_S)
        p_yes = slim.p_yes(judge_input(situation, pair))
        if p_yes >= NIGHTLY.judge_min_p_yes:
            return True
        self._parts.events.append_note_held(
            call, f"nightly:{Verdict.JUDGE_TOO_LOW.value}", {"judge_p_yes": p_yes}
        )
        return False

    def _down(self, project: str, down: JudgeOfflineError) -> JudgeOfflineError:
        """The loud message for a judge that failed: slow ones are not restarted, dead ones are."""
        if isinstance(down, JudgeSlowError):
            return JudgeOfflineError(
                f"symbiont checker slow: {down}, so no note was shown. It is still running."
            )
        return self._offline(project, down)

    def _offline(self, project: str, down: JudgeOfflineError) -> JudgeOfflineError:
        """The loud 503 for a trained checker that is down; starts it once from its record."""
        nightly = self._parts.nightly
        start = nightly.start_for(project) if nightly else None
        if nightly is None or start is None or nightly.revive is None:
            return JudgeOfflineError(
                f"symbiont checker offline: {down}. Start it with `symbiont nightly`."
            )
        earlier = self._started.get(project)
        if earlier is not None and earlier.poll() is None:
            # Alive but unreachable means the model is still loading; a second start would race it.
            return JudgeOfflineError("symbiont checker offline: it is still starting; ask again.")
        logfile = nightly.root / project / JUDGE_LOG
        try:
            self._started[project] = nightly.revive(start, logfile)
        except JudgeStartError as failed:
            hand = start.command_text("plug_judge_server.py")
            return JudgeOfflineError(f"symbiont checker offline: {failed}. By hand: {hand}")
        log.warning("%s: the checker was not running; started it (log %s)", project, logfile)
        return JudgeOfflineError(
            "symbiont checker offline: it was not running, so symbiont started it now; "
            "the model takes up to a minute to load, then ask again."
        )
