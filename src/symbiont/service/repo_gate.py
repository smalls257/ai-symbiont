"""The repository gate: what the service may do for a repository, by what the developer said.

A repository nobody answered for is not observed, and its first session says once what symbiont
does and how to answer. The gate also keeps a silenced kind of trouble silent, lets the
exact-repeat rule speak once per lesson per session, and makes the nightly announcement once.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.core.failure_signature import failure_signature
from symbiont.core.house_rules import (
    Supersession,
    retired_by_corrections,
)
from symbiont.core.repeat import RepeatNote, failed_now, repeat_note
from symbiont.core.rule_relevance import (
    MAX_RULE_NOTES,
    Rule,
    RuleMatch,
    relevant_rules,
    rules_of,
    situation_terms,
    why_none,
)
from symbiont.miner.changes import passed_check
from symbiont.miner.lesson_context import AuthoredLesson
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signature
from symbiont.records.schema import Kind, Record
from symbiont.service.nightly import NightlyJudges, NightlyReport, NightlyState
from symbiont.service.onboarding import (
    ONBOARDING,
    RELAY_TO_DEVELOPER,
    SESSION_START,
    Announcements,
    Lookups,
)
from symbiont.service.rule_voice import Occasion, RuleVoice
from symbiont.store.repos import Announced, RepoRegistry, RepoStance


@dataclass(frozen=True)
class Door:
    """Whether the service may observe, and what to tell the developer directly either way."""

    may_observe: bool
    announce: tuple[str, ...] = ()
    # For the session's model only; the developer reads `announce`.
    tell_model: tuple[str, ...] = ()


@dataclass(frozen=True)
class Spoken:
    """What the gate decided to say for one step: a note, or why it held back."""

    notes: tuple[RepeatNote, ...] = ()
    held: str | None = None
    # Rules that matched this work but were put aside for a later correction of the developer's.
    superseded: tuple[Supersession, ...] = ()
    # The once-per-session mark an exact-repeat note spent; withdrawn if the note was not shown.
    once: tuple[str, Signature] | None = None

    @property
    def note(self) -> RepeatNote | None:
        """The first note, or None when the gate stayed quiet."""
        return self.notes[0] if self.notes else None


def _relay_once(registry: RepoRegistry, project: str) -> tuple[str, ...]:
    """Ask the model to relay the question in its first reply, the first time only."""
    if registry.was_announced(project, Announced.ONBOARDING_RELAYED):
        return ()
    registry.announce(project, Announced.ONBOARDING_RELAYED)
    return (RELAY_TO_DEVELOPER,)


class RepoGate:
    """Decides, per repository, what the service may do; state lives in the registry file.

    Without a registry every repository is open and nothing is silenced.
    """

    def __init__(
        self,
        registry: RepoRegistry | None = None,
        nightly: NightlyJudges | None = None,
        lookups: Lookups | None = None,
    ) -> None:
        """Read answers from `registry`; `nightly` says when a first night is done."""
        self._lookups = lookups or Lookups()
        self.registry = registry
        self._news = None if registry is None else Announcements(registry, self._lookups, nightly)
        self._nightly = nightly
        self._said: set[tuple[str, Signature]] = set()
        self._unchecked_edits: set[str] = set()
        self._milestones: set[str] = set()
        self._voice = RuleVoice(self.silenced)

    def door(self, project: str, event: str) -> Door:
        """Open for a repository that said yes; otherwise closed, asking once at session start."""
        if self.registry is None:
            return Door(may_observe=True)
        stance = self.registry.stance(project)
        if stance is RepoStance.GIVEN:
            return Door(may_observe=True, announce=self._session_start_news(project, event))
        if stance is not None or event != SESSION_START:
            return Door(may_observe=False)
        return Door(
            may_observe=False,
            announce=(ONBOARDING,),
            tell_model=_relay_once(self.registry, project),
        )

    def silenced(self, project: str, trouble: Signature | None) -> bool:
        """Whether the developer muted this kind of trouble in this repository."""
        if trouble is None or self.registry is None:
            return False
        return (trouble.signal.value, *trouble.key) in self.registry.muted(project)

    def repeat(
        self, session_id: str, record: Record, earlier: Sequence[Record], lessons: Sequence[Lesson]
    ) -> RepeatNote | None:
        """The exact-repeat note for `record`, unless muted or already said in this session."""
        found = self._repeat(record, earlier, lessons)
        if found is None:
            return None
        if found.lesson is None:
            # An exact repeat always rests on a stored lesson; a note without one has no
            # signature to mute or to say once, so it is spoken as it came.
            return found
        signature = found.lesson.pain_point.signature
        if self.silenced(record.project, signature):
            return None
        if (session_id, signature) in self._said:
            return None
        self._said.add((session_id, signature))
        return found

    def forget_said(self, once: tuple[str, Signature] | None) -> None:
        """Withdraw the once-per-session mark of a recall that was not shown (checker down)."""
        self._said.discard(once)

    def status(self, project: str, lessons: Sequence[Lesson]) -> dict[str, object]:
        """What `/symbiont status` shows: the answer, the lesson count, silenced kinds, nightly."""
        stance = self.registry.stance(project) if self.registry else RepoStance.GIVEN
        return {
            "project": project,
            "repo": "unasked" if stance is None else stance.value,
            "lessons": len(lessons),
            "muted": len(self.registry.muted(project)) if self.registry else 0,
            "nightly": self.nightly_state(project, lessons),
        }

    def nightly_state(self, project: str, lessons: Sequence[Lesson]) -> dict[str, object]:
        """The nightly state as `status` and the dashboard show it (never, trained or stale)."""
        if self._nightly is None:
            return _report_json(NightlyReport(NightlyState.NEVER))
        return _report_json(self._nightly.report(project, lessons))

    def speak(
        self, session_id: str, record: Record, earlier: Sequence[Record], lessons: Sequence[Lesson]
    ) -> Spoken:
        """The exact-repeat note if the failure matches, else up to MAX_RULE_NOTES rules."""
        self._track_milestone(session_id, record)
        exact = self.repeat(session_id, record, earlier, lessons)
        if exact is not None and exact.lesson is not None:
            return Spoken((exact,), once=(session_id, exact.lesson.pain_point.signature))
        if exact is not None:
            return Spoken((exact,))
        return self._rule(session_id, record, lessons)

    def reached_milestone(self, session_id: str) -> bool:
        """Whether this session edited code and a later check passed: work worth reflecting on."""
        return session_id in self._milestones

    def _track_milestone(self, session_id: str, record: Record) -> None:
        """An edit leaves the session unchecked; the next passing check completes the milestone."""
        if record.kind is Kind.EDIT and record.exit_code != 1:
            self._unchecked_edits.add(session_id)
        elif passed_check(record) and session_id in self._unchecked_edits:
            self._unchecked_edits.discard(session_id)
            self._milestones.add(session_id)

    def speaks_only_on_match(self) -> bool:
        """Whether a note needs a stored lesson with this failure's signature (plugin mode)."""
        return self.registry is not None

    def _rule(self, session_id: str, record: Record, lessons: Sequence[Lesson]) -> Spoken:
        """The house rules once per session, then the best relevant rules for this work.

        A written lesson that a later correction supersedes is never said; the match it lost
        is returned so the event log can show why it stayed quiet.
        """
        touched = _touched_a_file(record)
        if self.registry is None or not (touched or _asks_for_rules(record)):
            return Spoken()
        project = record.project
        rules = rules_of(lessons, self._lookups.contexts(project), self._authored(project))
        if not rules:
            return Spoken()
        retired = retired_by_corrections(rules)
        if touched:
            notes, gone = self._voice.on_file(session_id, record, rules, retired)
            return Spoken(tuple(notes), superseded=gone)
        return self._prompt_rule(session_id, record, rules, retired)

    def _prompt_rule(
        self,
        session_id: str,
        record: Record,
        rules: Sequence[Rule],
        retired: dict[str, Supersession],
    ) -> Spoken:
        """House rules, then the rules relevant to a prompt or failure, minus the retired."""
        found = relevant_rules(
            _situation_text(record), record.files, rules, self._focus(record.project)
        )
        live = [match for match in found if match.rule.ident not in retired]
        gone = tuple(retired[m.rule.ident] for m in found if m.rule.ident in retired)
        leave_out = frozenset({*retired, *(match.rule.ident for match in live)})
        standing = self._voice.standing(session_id, record, rules, leave_out)
        room = MAX_RULE_NOTES - len(standing)
        when = Occasion(session_id, record.project, _trigger(record))
        notes = [
            *standing,
            *self._voice.fresh(when, live, room),
        ]
        if notes:
            return Spoken(tuple(notes), superseded=gone)
        return Spoken(held=_why_quiet(rules, live), superseded=gone)

    def _focus(self, project: str) -> frozenset[str]:
        """The terms the developer asked symbiont to pay attention to."""
        saved = self.registry.focus(project) if self.registry else None
        return (
            frozenset(situation_terms(" ".join(saved.get("keywords", []))))
            if saved
            else frozenset()
        )

    def _authored(self, project: str) -> list[AuthoredLesson]:
        """The written lessons of the repository."""
        return self._lookups.written(project)

    def _repeat(
        self, record: Record, earlier: Sequence[Record], lessons: Sequence[Lesson]
    ) -> RepeatNote | None:
        """The matching note, with the developer's words for the repository's lessons."""
        if self.registry is None:
            return None
        return repeat_note(record, earlier, lessons, self._lookups.contexts(record.project))

    def _session_start_news(self, project: str, event: str) -> tuple[str, ...]:
        """What a repository that said yes is told at session start."""
        if self._news is None or event != SESSION_START:
            return ()
        return self._news.at_session_start(project)


def _asks_for_rules(record: Record) -> bool:
    """Whether a prompt or a failed command opens the question of which rules apply."""
    return record.kind is Kind.USER_TURN or failed_now(record)


def _why_quiet(rules: Sequence[Rule], live: Sequence[RuleMatch]) -> str:
    """Why no rule spoke: nothing relevant, or what was relevant was already said."""
    if live:
        return "the related rule was already said for this prompt or failure"
    return why_none(rules)


def _touched_a_file(record: Record) -> bool:
    """Whether the record is a successful read or edit that names a file."""
    return record.kind in (Kind.READ, Kind.EDIT) and record.exit_code != 1 and bool(record.files)


def _situation_text(record: Record) -> str:
    """What the agent is working on: the prompt, or the failing command and its output."""
    return f"{record.command or ''} {record.raw}"


def _trigger(record: Record) -> str:
    """A prompt is one trigger per session; a failure is a new trigger when its message is new."""
    if record.kind is Kind.USER_TURN:
        return "prompt"
    found = failure_signature(record.raw)
    return found.message if found is not None else record.raw[:80]


def _report_json(report: NightlyReport) -> dict[str, object]:
    """A nightly report as the JSON object `/status` and the dashboard carry."""
    return {
        "state": report.state.value,
        "lessons": report.lessons,
        "trained_at": report.trained_at,
        "sentence": report.sentence(),
    }
