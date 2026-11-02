"""The service without a transport: routes in, (status, body) out."""

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from symbiont.core.agree import AGREE, NIGHTLY, Verdict, agree
from symbiont.core.features import featurise
from symbiont.core.judge_format import fix_commands
from symbiont.core.memory_note import note_request, recall_request
from symbiont.core.note_rules import may_speak
from symbiont.core.notes import NoteKind, render, render_lesson
from symbiont.core.recall import relevant_lessons
from symbiont.core.repeat import RepeatNote
from symbiont.core.slot import NO_HISTORY, Decider, Decision, Outcome, Situation
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint
from symbiont.miner.secrets import scrub
from symbiont.miner.twins import merge_twins
from symbiont.readers import READERS, Reader
from symbiont.readers.errors import ReadError
from symbiont.records.holdout import HoldOutViolationError, UnrecognisedTaskIdError
from symbiont.records.privacy import OwnHistoryConsent
from symbiont.records.schema import Record
from symbiont.service.events import Call, EventLog, MemoryCost
from symbiont.service.follow_up import FollowUp, ShownNote
from symbiont.service.judge_model import JudgeModel, JudgeOfflineError
from symbiont.service.memory_model import (
    MemoryModel,
    MemoryModelOfflineError,
    MemoryReply,
    may_answer_spark,
)
from symbiont.service.nightly import NightlyJudges
from symbiont.service.repo_gate import Door, RepoGate
from symbiont.service.request_shapes import (
    BadRequestError,
    as_object,
    hook_of,
    named_project,
    observed,
    project_of,
    require_keys,
    source_of,
    spark_bound,
)
from symbiont.store.local import SparkPrivacyViolationError, Store
from symbiont.store.mining import MiningRules, UnknownReaderError, read_source, remine_with_read

log = logging.getLogger("symbiont.service")
SPARK_WITHHELD = "private history withheld from Spark"
NOTHING_MATCHES = "nothing in this project's history matches that question"
RECALL_KEYS = frozenset({"question", "project", "spark_bound"})
OBSERVE_REQUIRED = frozenset({"harness", "session_id", "event", "payload"})
OBSERVE_KEYS = OBSERVE_REQUIRED | {"spark_bound"}
LEARN_KEYS = frozenset({"reader", "session_log_path", "project"})
SILENCED = "the developer silenced this kind of note"
HELD_BY_RULE = "the note budget is spent or the last note was too recent"


class ServiceMode(StrEnum):
    """What the service may say on /observe; recall-only ships when no learner earns warnings."""

    WARN_AND_RECALL = "warn_and_recall"
    RECALL_ONLY = "recall_only"


_KINDS_BY_MODE = {
    ServiceMode.WARN_AND_RECALL: tuple(NoteKind),
    ServiceMode.RECALL_ONLY: (NoteKind.RECALL,),
}


@dataclass(frozen=True)
class Response:
    """What a transport sends back."""

    status: int
    body: dict[str, Any]


@dataclass(frozen=True)
class ServiceParts:
    """Everything a service is wired from; the filler is whatever `decider` is."""

    store: Store
    decider: Decider
    events: EventLog
    mode: ServiceMode = ServiceMode.WARN_AND_RECALL
    held_out_tasks: frozenset[str] = frozenset()
    # Reader name -> reader; /learn names one, and mining re-reads every source through them.
    readers: Mapping[str, Reader] = field(default_factory=lambda: dict(READERS))
    # Route A: when set, notes and answers for the projects it learned come from this model.
    memory: MemoryModel | None = None
    # Plug round 4: when set, /recall shows a stored note only if ranker and judge agree.
    judge: JudgeModel | None = None
    # The continuous loop: after a repository's first night its own adapter judges (bar 0.98).
    nightly: NightlyJudges | None = None
    # The user's own-history setting (store.consent); what a Spark-bound call may rest on.
    consent: OwnHistoryConsent = OwnHistoryConsent.WITHHELD
    # The per-repository answers; when set, a repository that did not say yes is not observed.
    gate: RepoGate = field(default_factory=RepoGate)


class SparkWithheldError(PermissionError):
    """A Spark-bound answer could not be shown to rest only on Spark-safe records."""


class Service:
    """Observe, recall and learn over one store and one decider."""

    def __init__(self, parts: ServiceParts) -> None:
        """Start with the decider's initial state."""
        self._parts = parts
        self._state = parts.decider.initial_state(0)
        self._prefixes: dict[tuple[str, str], list[Record]] = {}
        self._spoken: dict[tuple[str, str], list[int]] = {}
        self._one_call_at_a_time = threading.Lock()
        self._follow_up = FollowUp(parts.events)

    def respond(self, route: str, payload: Any) -> Response:
        """Answer one request; a refusal is a status plus a reason, and an event."""
        with self._one_call_at_a_time:
            return self._respond_locked(route, payload)

    def _respond_locked(self, route: str, payload: Any) -> Response:
        """Route one request; unknown routes are refused with 404."""
        name = route.strip("/")
        call = Call(name, hook_of(name, payload), project_of(payload))
        routes = {
            "observe": self._observe,
            "recall": self._recall,
            "learn": self._learn,
            "status": lambda request, call: _status(self._parts, self._lessons, request),
        }
        if name not in routes:
            return self._refuse(call, 404, f"no such route: {route}")
        try:
            return routes[name](as_object(payload), call)
        except BadRequestError as exc:
            return self._refuse(call, 400, str(exc))
        except (SparkPrivacyViolationError, SparkWithheldError):
            return self._refuse(call, 409, SPARK_WITHHELD)
        except HoldOutViolationError as exc:
            return self._refuse(call, 409, str(exc))
        except UnrecognisedTaskIdError as exc:
            return self._refuse(call, 422, str(exc))
        except MemoryModelOfflineError as exc:
            return self._refuse(call, 503, str(exc))
        except Exception:
            log.exception("service call failed: %s", name)
            return self._refuse(call, 500, "internal error; see the service log")

    def _refuse(self, call: Call, status: int, reason: str) -> Response:
        """Log the failure and return it as an error response."""
        self._parts.events.append_failure(call, status, reason)
        return Response(status, {"error": reason})

    def _observe(self, request: dict[str, Any], call: Call) -> Response:
        """Record one hook observation and answer with the decider's note."""
        require_keys(request, OBSERVE_KEYS, OBSERVE_REQUIRED)
        project, record = observed(request["payload"])
        gate = self._parts.gate
        door = gate.door(project, request["event"])
        if not door.may_observe:
            return _said(door, [])
        lessons = self._lessons(request, project)
        key = (request["harness"], request["session_id"])
        prefix = self._prefixes.setdefault(key, [])
        prefix.append(record)
        self._follow_up.observed(call, project, record)
        spoken = gate.repeat(request["session_id"], record, prefix[:-1], lessons)
        if spoken is not None:
            return _repeat_response(self._parts.events, call, spoken, door)
        # No raw history is stored, so there are no earlier records to recall from here.
        history = tuple(lesson.pain_point for lesson in lessons)
        situation = Situation(project, tuple(prefix), history, ())
        decision = self._parts.decider.decide(featurise(situation), situation, self._state)
        if spark_bound(request):
            _refuse_untraceable(decision, lessons)
        if gate.silenced(project, decision.trouble):
            self._parts.events.append_quiet(call, decision, SILENCED)
            return _said(door, [])
        warns = self._parts.mode is ServiceMode.WARN_AND_RECALL
        memory = self._memory_for(request, project) if decision.trouble and warns else None
        if memory is not None:
            return self._memory_observe(request, decision, memory, call)
        notes = render(decision, kinds=_KINDS_BY_MODE[self._parts.mode], lessons=lessons)
        self._parts.events.append_decision(call, decision, notes)
        return _said(door, notes)

    def _memory_for(self, request: dict[str, Any], project: str) -> MemoryModel | None:
        """The memory model that may answer for `project`, or None; Spark needs its own adapter."""
        memory = self._parts.memory
        if memory is None or not memory.knows(project):
            return None
        if spark_bound(request) and not may_answer_spark(memory.provenance, self._parts.consent):
            raise SparkWithheldError
        return memory

    def _memory_observe(
        self, request: dict[str, Any], decision: Decision, memory: MemoryModel, call: Call
    ) -> Response:
        """Option A decides whether to speak; the memory model writes what is said."""
        key, to_spark = (request["harness"], request["session_id"]), spark_bound(request)
        position = len(self._prefixes[key]) - 1
        spoken = self._spoken.setdefault(key, [])
        trouble = decision.trouble
        if trouble is None or not may_speak(spoken, position):
            self._parts.events.append_quiet(call, decision, HELD_BY_RULE)
            return Response(200, {"notes": []})
        reply = memory.write_line(note_request(self._prefixes[key][-1].project, trouble))
        spoken.append(position)
        line = scrub(reply.line) if to_spark else reply.line
        self._parts.events.append_memory_note(call, decision, line, _cost(reply))
        return Response(200, {"notes": [line]})

    def _lessons(self, request: dict[str, Any], project: str) -> list[Lesson]:
        """The project's lessons, through the Spark view when the request is Spark-bound."""
        store = self._parts.store
        if spark_bound(request):
            return store.spark_view(self._parts.consent).lessons(project)
        return store.lessons(project)

    def _recall(self, request: dict[str, Any], call: Call) -> Response:
        """Answer a plain question from the project's sessions."""
        require_keys(request, RECALL_KEYS, frozenset({"question", "project"}))
        project, question = request["project"], request["question"]
        if not (isinstance(project, str) and isinstance(question, str)):
            raise BadRequestError("question and project must be text")
        lessons = self._lessons(request, project)
        if lessons and (self._parts.judge or self._parts.nightly):
            return self._agreed_recall(call, project, question, lessons)
        memory = self._memory_for(request, project)
        if memory is not None:
            reply = memory.write_line(recall_request(project, question))
            line = scrub(reply.line) if spark_bound(request) else reply.line
            self._parts.events.append_memory_note(call, None, line, _cost(reply))
            return Response(200, {"answer": line, "records": []})
        if not lessons:
            return self._answered(call, NO_HISTORY, [])
        found = relevant_lessons(question, lessons)
        notes = list(dict.fromkeys(render_lesson(lesson) for lesson in found))
        return self._answered(call, " ".join(notes) or NOTHING_MATCHES, found)

    def _agreed_recall(
        self, call: Call, project: str, question: str, lessons: list[Lesson]
    ) -> Response:
        """The agree rule's stored note, or NOTHING_MATCHES; a down judge raises (503)."""
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
            return self._answered(call, outcome.note, [outcome.lesson])
        numbers = {
            "ranker_score": outcome.ranker_score,
            "ranker_cut": outcome.ranker_cut,
            "ceiling": outcome.ceiling,
            "judge_p_yes": outcome.judge_p_yes,
        }
        self._parts.events.append_note_held(call, f"{rule}:{outcome.verdict.value}", numbers)
        return self._answered(call, NOTHING_MATCHES, [])

    def _answered(self, call: Call, answer: str, found: Sequence[Lesson]) -> Response:
        """Log the answer with the records it cites and return it."""
        refs = list(dict.fromkeys(ref for lesson in found for ref in lesson.pain_point.record_refs))
        self._parts.events.append(call, None, refs, [answer])
        return Response(200, {"answer": answer, "records": [list(ref) for ref in refs]})

    def _learn(self, request: dict[str, Any], call: Call) -> Response:
        """Load a finished session log into the store and learn from it."""
        require_keys(request, LEARN_KEYS, LEARN_KEYS)
        source = source_of(request)
        parts = self._parts
        rules = MiningRules(parts.readers, parts.held_out_tasks)
        try:
            records = read_source(source, parts.readers)
            remine_with_read(parts.store, source.project, rules, {source: records})
        except (OSError, ReadError, UnknownReaderError) as exc:
            raise BadRequestError(f"cannot read the session log: {exc}") from exc
        learned = self._learn_project(source.project, records)
        parts.events.append(call, None, [], [f"learned from {learned} steps"])
        return Response(200, {"learned_steps": learned})

    def _learn_project(self, project: str, records: list[Record]) -> int:
        """Replay one project's records through the decider; returns the count learned."""
        decider = self._parts.decider
        history = tuple(self._parts.store.pain_points(project))
        troubles = _troubles_by_step(list(history), records)
        mine = [r for r in records if r.project == project]
        for i, record in enumerate(mine):
            situation = Situation(project, tuple(mine[: i + 1]), history, ())
            x = featurise(situation)
            for outcome in _outcomes(record, troubles):
                self._state = decider.learn(x, outcome, self._state)
        return len(mine)


def _status(
    parts: ServiceParts, lessons_of: Callable[..., list[Lesson]], request: dict[str, Any]
) -> Response:
    """The repository's state for `symbiont status`; it changes nothing."""
    name = named_project(request)
    return Response(200, parts.gate.status(name, lessons_of(request, name)))


def _repeat_response(events: EventLog, call: Call, found: RepeatNote, door: Door) -> Response:
    """The exact-repeat note, logged with the kind of trouble it rests on."""
    pain = found.lesson.pain_point
    events.append(call, pain.signature, list(pain.record_refs), [found.sentence])
    return _said(door, [found.sentence])


def _said(door: Door, notes: list[str]) -> Response:
    """The notes for the agent, plus what to tell the developer directly when there is any."""
    body: dict[str, Any] = {"notes": notes}
    if door.announce:
        body["announce"] = list(door.announce)
    return Response(200, body)


def _cost(reply: MemoryReply) -> MemoryCost:
    """The prompt size and time of a memory reply, as logged."""
    return MemoryCost(reply.prompt_chars, round(reply.elapsed_ms, 1))


def _refuse_untraceable(decision: Decision, lessons: Sequence[Lesson]) -> None:
    """A Spark-bound note must rest only on lessons the Spark view returned.

    A trouble with no cited pain point, a pain point no such lesson backs (learned
    from another project), or a recalled record cannot be shown to be Spark-safe.
    """
    backed = {lesson.pain_point for lesson in lessons}
    if decision.trouble is not None and not decision.why:
        raise SparkWithheldError
    if decision.recall or any(pain not in backed for pain in decision.why):
        raise SparkWithheldError


def _outcomes(record: Record, troubles: dict[tuple[str, int], list[PainPoint]]) -> list[Outcome]:
    """What followed a record: the pain points it hit, or a plain no-trouble outcome."""
    found = troubles.get((record.session_id, record.step), [])
    if not found:
        return [
            Outcome(
                pain_point_followed=False,
                signature=None,
                session_id=record.session_id,
                step=record.step,
            )
        ]
    return [
        Outcome(
            pain_point_followed=True, signature=p.signature, session_id=p.session_id, step=p.step
        )
        for p in found
    ]


def _troubles_by_step(
    mined: list[PainPoint], records: list[Record]
) -> dict[tuple[str, int], list[PainPoint]]:
    """Pain points mined from the given sessions, keyed by (session, step)."""
    sessions = {r.session_id for r in records}
    by_step: dict[tuple[str, int], list[PainPoint]] = {}
    for pain in mined:
        if pain.session_id in sessions:
            by_step.setdefault((pain.session_id, pain.step), []).append(pain)
    return by_step
