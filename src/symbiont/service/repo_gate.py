"""The repository gate: what the service may do for a repository, by what the developer said.

A repository nobody answered for is not observed, and its first session says once what symbiont
does and how to answer. The gate also keeps a silenced kind of trouble silent, lets the
exact-repeat rule speak once per lesson per session, and makes the nightly announcement once.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.core.failure_signature import failure_signature
from symbiont.core.repeat import RepeatNote, failed_now, repeat_note
from symbiont.core.rule_relevance import (
    Rule,
    relevant_rules,
    rule_sentence,
    rules_of,
    situation_terms,
    why_none,
)
from symbiont.miner.changes import passed_check
from symbiont.miner.lesson_context import AuthoredLesson
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signature
from symbiont.records.schema import Kind, Record
from symbiont.service.nightly import NightlyJudges
from symbiont.service.onboarding import (
    ONBOARDING,
    SESSION_START,
    Announcements,
    Lookups,
)
from symbiont.store.repos import RepoRegistry, RepoStance


@dataclass(frozen=True)
class Door:
    """Whether the service may observe, and what to tell the developer directly either way."""

    may_observe: bool
    announce: tuple[str, ...] = ()


@dataclass(frozen=True)
class Spoken:
    """What the gate decided to say for one step: a note, or why it held back."""

    note: RepeatNote | None = None
    held: str | None = None


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
        self._rules_said: set[tuple[str, str, str]] = set()

    def door(self, project: str, event: str) -> Door:
        """Open for a repository that said yes; otherwise closed, asking once at session start."""
        if self.registry is None:
            return Door(may_observe=True)
        stance = self.registry.stance(project)
        if stance is RepoStance.GIVEN:
            return Door(may_observe=True, announce=self._session_start_news(project, event))
        asked_now = stance is None and event == SESSION_START
        return Door(may_observe=False, announce=(ONBOARDING,) if asked_now else ())

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

    def status(self, project: str, lessons: Sequence[Lesson]) -> dict[str, object]:
        """What `/symbiont status` shows: the answer, the lesson count, silenced kinds, nightly."""
        stance = self.registry.stance(project) if self.registry else RepoStance.GIVEN
        return {
            "project": project,
            "repo": "unasked" if stance is None else stance.value,
            "lessons": len(lessons),
            "muted": len(self.registry.muted(project)) if self.registry else 0,
            "nightly": self._nightly is not None and self._nightly.has_record(project),
        }

    def speak(
        self, session_id: str, record: Record, earlier: Sequence[Record], lessons: Sequence[Lesson]
    ) -> Spoken:
        """The exact-repeat note if the failure matches, else at most one relevant rule."""
        self._track_milestone(session_id, record)
        exact = self.repeat(session_id, record, earlier, lessons)
        if exact is not None:
            return Spoken(exact)
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
        """One rule relevant to this prompt or failure, never twice for the same trigger."""
        if self.registry is None or not (record.kind is Kind.USER_TURN or failed_now(record)):
            return Spoken()
        project = record.project
        rules = rules_of(lessons, self._lookups.contexts(project), self._authored(project))
        if not rules:
            return Spoken()
        found = relevant_rules(_situation_text(record), record.files, rules, self._focus(project))
        if not found:
            return Spoken(held=why_none(rules))
        trigger = _trigger(record)
        for match in found:
            key = (session_id, match.rule.ident, trigger)
            if key in self._rules_said or self._muted_rule(project, match.rule):
                continue
            self._rules_said.add(key)
            note = RepeatNote(
                rule_sentence(match.rule.words), match.rule.lesson, "rule: " + match.why
            )
            return Spoken(note)
        return Spoken(held="the related rule was already said for this prompt or failure")

    def _muted_rule(self, project: str, rule: Rule) -> bool:
        """Whether the developer silenced the kind of trouble behind a mined rule."""
        return rule.lesson is not None and self.silenced(project, rule.lesson.pain_point.signature)

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


def _situation_text(record: Record) -> str:
    """What the agent is working on: the prompt, or the failing command and its output."""
    return f"{record.command or ''} {record.raw}"


def _trigger(record: Record) -> str:
    """A prompt is one trigger per session; a failure is a new trigger when its message is new."""
    if record.kind is Kind.USER_TURN:
        return "prompt"
    found = failure_signature(record.raw)
    return found.message if found is not None else record.raw[:80]
