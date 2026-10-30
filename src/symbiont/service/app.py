"""The service without a transport: routes in, (status, body) out."""

import io
import json
import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from symbiont.core.agree import AGREE, NIGHTLY, Verdict, agree
from symbiont.core.features import featurise
from symbiont.core.memory_note import note_request, recall_request
from symbiont.core.note_rules import may_speak
from symbiont.core.notes import NoteKind, render, render_lesson
from symbiont.core.recall import relevant_lessons
from symbiont.core.slot import NO_HISTORY, Decider, Decision, Outcome, Situation
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint
from symbiont.miner.secrets import scrub
from symbiont.miner.twins import merge_twins
from symbiont.readers import READERS, Reader
from symbiont.readers.errors import ReadError
from symbiont.records.holdout import HoldOutViolationError, UnrecognisedTaskIdError
from symbiont.records.privacy import OwnHistoryConsent
from symbiont.records.schema import Record, RecordFormatError, load_jsonl
from symbiont.service.events import Call, EventLog, MemoryCost
from symbiont.service.judge_model import JudgeModel, JudgeOfflineError
from symbiont.service.memory_model import (
    MemoryModel,
    MemoryModelOfflineError,
    MemoryReply,
    may_answer_spark,
)
from symbiont.service.nightly import NightlyJudges
from symbiont.store.local import Source, SparkPrivacyViolationError, Store
from symbiont.store.mining import MiningRules, UnknownReaderError, read_source, remine_with_read

log = logging.getLogger("symbiont.service")
SPARK_WITHHELD = "private history withheld from Spark"
NOTHING_MATCHES = "nothing in this project's history matches that question"
RECALL_KEYS = frozenset({"question", "project", "spark_bound"})
OBSERVE_REQUIRED = frozenset({"harness", "session_id", "event", "payload"})
OBSERVE_KEYS = OBSERVE_REQUIRED | {"spark_bound"}
LEARN_KEYS = frozenset({"reader", "session_log_path", "project"})
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


class SparkWithheldError(PermissionError):
    """A Spark-bound answer could not be shown to rest only on Spark-safe records."""


class BadRequestError(ValueError):
    """A request that does not have the shape its route takes."""


class Service:
    """Observe, recall and learn over one store and one decider."""

    def __init__(self, parts: ServiceParts) -> None:
        """Start with the decider's initial state and no session prefixes."""
        self._parts = parts
        self._state = parts.decider.initial_state(0)
        self._prefixes: dict[tuple[str, str], list[Record]] = {}
        self._spoken: dict[tuple[str, str], list[int]] = {}
        self._one_call_at_a_time = threading.Lock()

    def respond(self, route: str, payload: Any) -> Response:
        """Answer one request; a refusal is a status plus a reason, and an event."""
        with self._one_call_at_a_time:
            return self._respond_locked(route, payload)

    def _respond_locked(self, route: str, payload: Any) -> Response:
        """Route one request; unknown routes are refused with 404."""
        name = route.strip("/")
        call = Call(name, _hook_of(name, payload))
        routes = {"observe": self._observe, "recall": self._recall, "learn": self._learn}
        if name not in routes:
            return self._refuse(call, 404, f"no such route: {route}")
        try:
            return routes[name](_object(payload), call)
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
        _require_keys(request, OBSERVE_KEYS, OBSERVE_REQUIRED)
        project, record = _observed(request["payload"])
        lessons = self._lessons(request, project)
        key = (request["harness"], request["session_id"])
        prefix = self._prefixes.setdefault(key, [])
        prefix.append(record)
        # No raw history is stored, so there are no earlier records to recall from here.
        history = tuple(lesson.pain_point for lesson in lessons)
        situation = Situation(project, tuple(prefix), history, ())
        decision = self._parts.decider.decide(featurise(situation), situation, self._state)
        if _spark_bound(request):
            _refuse_untraceable(decision, lessons)
        warns = self._parts.mode is ServiceMode.WARN_AND_RECALL
        memory = self._memory_for(request, project) if decision.trouble and warns else None
        if memory is not None:
            return self._memory_observe(request, decision, memory, call)
        notes = render(decision, kinds=_KINDS_BY_MODE[self._parts.mode], lessons=lessons)
        self._parts.events.append_decision(call, decision, notes)
        return Response(200, {"notes": notes})

    def _memory_for(self, request: dict[str, Any], project: str) -> MemoryModel | None:
        """The memory model that may answer for `project`, or None; Spark needs its own adapter."""
        memory = self._parts.memory
        if memory is None or not memory.knows(project):
            return None
        if _spark_bound(request) and not may_answer_spark(memory.provenance, self._parts.consent):
            raise SparkWithheldError
        return memory

    def _memory_observe(
        self, request: dict[str, Any], decision: Decision, memory: MemoryModel, call: Call
    ) -> Response:
        """Option A decides whether to speak; the memory model writes what is said."""
        key, spark_bound = (request["harness"], request["session_id"]), _spark_bound(request)
        position = len(self._prefixes[key]) - 1
        spoken = self._spoken.setdefault(key, [])
        trouble = decision.trouble
        if trouble is None or not may_speak(spoken, position):
            self._parts.events.append_quiet(call, decision, HELD_BY_RULE)
            return Response(200, {"notes": []})
        reply = memory.write_line(note_request(self._prefixes[key][-1].project, trouble))
        spoken.append(position)
        line = scrub(reply.line) if spark_bound else reply.line
        self._parts.events.append_memory_note(call, decision, line, _cost(reply))
        return Response(200, {"notes": [line]})

    def _lessons(self, request: dict[str, Any], project: str) -> list[Lesson]:
        """The project's lessons, through the Spark view when the request is Spark-bound."""
        store = self._parts.store
        if _spark_bound(request):
            return store.spark_view(self._parts.consent).lessons(project)
        return store.lessons(project)

    def _recall(self, request: dict[str, Any], call: Call) -> Response:
        """Answer a plain question from the project's sessions."""
        _require_keys(request, RECALL_KEYS, frozenset({"question", "project"}))
        project, question = request["project"], request["question"]
        if not (isinstance(project, str) and isinstance(question, str)):
            raise BadRequestError("question and project must be text")
        lessons = self._lessons(request, project)
        if lessons and (self._parts.judge or self._parts.nightly):
            return self._agreed_recall(call, project, question, lessons)
        memory = self._memory_for(request, project)
        if memory is not None:
            reply = memory.write_line(recall_request(project, question))
            line = scrub(reply.line) if _spark_bound(request) else reply.line
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
        if judge is None:
            raise JudgeOfflineError("no first-night judge is configured (--judge-url)")
        outcome = agree(question, project, merged, judge.p_yes, bars)
        if outcome.verdict is Verdict.AGREED and outcome.lesson and outcome.note:
            return self._answered(call, outcome.note, [outcome.lesson])
        return self._answered(call, NOTHING_MATCHES, [])

    def _answered(self, call: Call, answer: str, found: Sequence[Lesson]) -> Response:
        """Log the answer with the records it cites and return it."""
        refs = list(dict.fromkeys(ref for lesson in found for ref in lesson.pain_point.record_refs))
        self._parts.events.append(call, None, refs, [answer])
        return Response(200, {"answer": answer, "records": [list(ref) for ref in refs]})

    def _learn(self, request: dict[str, Any], call: Call) -> Response:
        """Load a finished session log into the store and learn from it."""
        _require_keys(request, LEARN_KEYS, LEARN_KEYS)
        source = _source_of(request)
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


def _spark_bound(request: dict[str, Any]) -> bool:
    """Absent means local; anything but a real bool is refused, never guessed."""
    value = request.get("spark_bound", False)
    if not isinstance(value, bool):
        raise BadRequestError("spark_bound must be true or false")
    return value


def _hook_of(route: str, payload: Any) -> str:
    """The hook name to log: the event for observe, otherwise the route."""
    event = payload.get("event") if isinstance(payload, dict) else None
    return event if route == "observe" and isinstance(event, str) else route


def _object(payload: Any) -> dict[str, Any]:
    """The payload as a dict, or BadRequestError."""
    if not isinstance(payload, dict):
        raise BadRequestError("the request body must be a JSON object")
    return payload


def _require_keys(
    request: dict[str, Any], allowed: frozenset[str], required: frozenset[str]
) -> None:
    """Raise BadRequestError for unexpected or missing request fields."""
    extra = sorted(set(request) - allowed)
    if extra:
        raise BadRequestError(f"unexpected fields: {', '.join(extra)}")
    missing = sorted(required - set(request))
    if missing:
        raise BadRequestError(f"missing fields: {', '.join(missing)}")


def _observed(payload: Any) -> tuple[str, Record]:
    """The project and record carried by an observe payload."""
    body = _object(payload)
    try:
        record = next(load_jsonl(io.StringIO(json.dumps(body.get("record")))))
    except (RecordFormatError, StopIteration) as exc:
        raise BadRequestError(f"payload.record is not a record: {exc}") from exc
    return record.project, record


def _source_of(request: dict[str, Any]) -> Source:
    """The log source a learn request names; all three fields must be text."""
    reader, path, project = request["reader"], request["session_log_path"], request["project"]
    if not all(isinstance(value, str) for value in (reader, path, project)):
        raise BadRequestError("reader, session_log_path and project must be text")
    return Source(project, reader, path)
