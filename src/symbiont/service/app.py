"""The service without a transport: routes in, (status, body) out."""

import io
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from symbiont.core.features import featurise
from symbiont.core.notes import NoteKind, render
from symbiont.core.recall import relevant_records
from symbiont.core.slot import NO_HISTORY, Decider, Decision, Outcome, Situation
from symbiont.miner.painpoint import PainPoint
from symbiont.records.holdout import HoldOutViolationError
from symbiont.records.schema import Record, RecordFormatError, load_jsonl
from symbiont.service.events import EventLog
from symbiont.store.local import SparkPrivacyViolationError, Store

SPARK_WITHHELD = "private history withheld from Spark"
NOTHING_MATCHES = "nothing in this project's history matches that question"
RECALL_KEYS = frozenset({"question", "project", "spark_bound"})
OBSERVE_REQUIRED = frozenset({"harness", "session_id", "event", "payload"})
OBSERVE_KEYS = OBSERVE_REQUIRED | {"spark_bound"}
LEARN_KEYS = frozenset({"session_log_path"})


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


class BadRequestError(ValueError):
    """A request that does not have the shape its route takes."""


class Service:
    """Observe, recall and learn over one store and one decider."""

    def __init__(self, parts: ServiceParts) -> None:
        self._parts = parts
        self._state = parts.decider.initial_state(0)
        self._prefixes: dict[tuple[str, str], list[Record]] = {}

    def respond(self, route: str, payload: Any) -> Response:
        """Answer one request; a refusal is a status plus a reason, and an event."""
        hook = route.strip("/")
        routes = {"observe": self._observe, "recall": self._recall, "learn": self._learn}
        if hook not in routes:
            return self._refuse(hook, 404, f"no such route: {route}")
        try:
            return routes[hook](_object(payload))
        except BadRequestError as exc:
            return self._refuse(hook, 400, str(exc))
        except SparkPrivacyViolationError:
            return self._refuse(hook, 409, SPARK_WITHHELD)
        except HoldOutViolationError as exc:
            return self._refuse(hook, 409, str(exc))

    def _refuse(self, hook: str, status: int, reason: str) -> Response:
        self._parts.events.append_failure(hook, status, reason)
        return Response(status, {"error": reason})

    def _observe(self, request: dict[str, Any]) -> Response:
        _require_keys(request, OBSERVE_KEYS, OBSERVE_REQUIRED)
        project, record = _observed(request["payload"])
        prefix = self._prefixes.setdefault((request["harness"], request["session_id"]), [])
        prefix.append(record)
        history = tuple(self._parts.store.pain_points(project))
        situation = Situation(project, tuple(prefix), history, ())
        decider = self._parts.decider
        decision = decider.decide(featurise(situation), situation, self._state)
        if request.get("spark_bound") is True:
            self._refuse_private_citations(decision)
        notes = render(decision, kinds=_KINDS_BY_MODE[self._parts.mode])
        self._parts.events.append_decision(request["event"], decision, notes)
        return Response(200, {"notes": notes})

    def _refuse_private_citations(self, decision: Decision) -> None:
        cited = [ref for pain in decision.why for ref in pain.record_refs]
        cited += [(r.session_id, r.step) for r in decision.recall]
        self._parts.store.spark_view().records_for(cited)

    def _recall(self, request: dict[str, Any]) -> Response:
        _require_keys(request, RECALL_KEYS, frozenset({"question", "project"}))
        project, question = request["project"], request["question"]
        store = self._parts.store
        reader = store.spark_view() if request.get("spark_bound") is True else store
        sessions = reader.sessions(project)
        if not sessions:
            return self._answered(NO_HISTORY, [])
        found = relevant_records(question, (r for s in sessions for r in s))
        quiet = Decision(None, (), tuple(found), None if found else NOTHING_MATCHES)
        notes = render(quiet, kinds=[NoteKind.RECALL])
        return self._answered(" ".join(notes) or NOTHING_MATCHES, found)

    def _answered(self, answer: str, found: list[Record]) -> Response:
        refs = [(r.session_id, r.step) for r in found]
        self._parts.events.append("recall", None, refs, [answer])
        return Response(200, {"answer": answer, "records": [list(ref) for ref in refs]})

    def _learn(self, request: dict[str, Any]) -> Response:
        _require_keys(request, LEARN_KEYS, LEARN_KEYS)
        records = _read_session_log(request["session_log_path"])
        parts = self._parts
        parts.store.add_records(records, held_out_tasks=parts.held_out_tasks)
        learned = 0
        for project in sorted({r.project for r in records}):
            parts.store.mine(project, references={})
            learned += self._learn_project(project, records)
        parts.events.append("learn", None, [], [f"learned from {learned} steps"])
        return Response(200, {"learned_steps": learned})

    def _learn_project(self, project: str, records: list[Record]) -> int:
        decider = self._parts.decider
        troubles = _troubles_by_step(self._parts.store.pain_points(project), records)
        history = tuple(self._parts.store.pain_points(project))
        mine = [r for r in records if r.project == project]
        for i, record in enumerate(mine):
            situation = Situation(project, tuple(mine[: i + 1]), history, ())
            x = featurise(situation)
            for outcome in _outcomes(record, troubles):
                self._state = decider.learn(x, outcome, self._state)
        return len(mine)


def _outcomes(record: Record, troubles: dict[tuple[str, int], list[PainPoint]]) -> list[Outcome]:
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
    sessions = {r.session_id for r in records}
    by_step: dict[tuple[str, int], list[PainPoint]] = {}
    for pain in mined:
        if pain.session_id in sessions:
            by_step.setdefault((pain.session_id, pain.step), []).append(pain)
    return by_step


def _object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BadRequestError("the request body must be a JSON object")
    return payload


def _require_keys(
    request: dict[str, Any], allowed: frozenset[str], required: frozenset[str]
) -> None:
    extra = sorted(set(request) - allowed)
    if extra:
        raise BadRequestError(f"unexpected fields: {', '.join(extra)}")
    missing = sorted(required - set(request))
    if missing:
        raise BadRequestError(f"missing fields: {', '.join(missing)}")


def _observed(payload: Any) -> tuple[str, Record]:
    body = _object(payload)
    try:
        record = next(load_jsonl(io.StringIO(json.dumps(body.get("record")))))
    except (RecordFormatError, StopIteration) as exc:
        raise BadRequestError(f"payload.record is not a record: {exc}") from exc
    return record.project, record


def _read_session_log(path: str) -> list[Record]:
    try:
        with Path(path).open(encoding="utf-8") as log:
            return list(load_jsonl(log))
    except OSError as exc:
        raise BadRequestError(f"cannot read the session log: {exc}") from exc
    except RecordFormatError as exc:
        raise BadRequestError(f"the session log is not records: {exc}") from exc
