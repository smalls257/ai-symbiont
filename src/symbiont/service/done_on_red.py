"""The done-on-red guard: a Stop is held when the session's last run of a check is still failing.

`miner/unfinished_check.py` reads the session's records; the Stop hook is a thin client. Every
decision is an event with its reason. Muse Code reports `stop_hook_active` true on every Stop after
the first hook block of a turn, so the host flag is logged but not trusted: the guard keeps its own
state. It holds a session at most MAX_HOLDS times, and again only after a newer failing run, so a
model that cannot fix a check is never looped, and it never holds the reflection turn's Stop.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from symbiont.miner.credential_scrub import scrub
from symbiont.miner.unfinished_check import UnfinishedCheck, unfinished_check
from symbiont.records.schema import Record
from symbiont.service.events import Call, EventLog
from symbiont.service.repo_gate import RepoGate
from symbiont.service.request_shapes import BadRequestError, require_keys

GUARD_REQUIRED = frozenset({"project", "session_id", "harness"})
GUARD_KEYS = GUARD_REQUIRED | {"stop_hook_active"}
# Two: the model may be wrong once and right after seeing the failure; a third hold would only
# repeat a message it has read, and a check it cannot fix (a failure present before its edits)
# would loop the session.
MAX_HOLDS = 2
STOP_HOOK = "Stop"
SessionKey = tuple[str, str]  # (harness, session id), as the service keys its records


class DoneOnRedGuard:
    """Decides, per Stop, whether to block because a check is still red; remembers it did."""

    def __init__(
        self,
        gate: RepoGate,
        events: EventLog,
        session_records: Mapping[SessionKey, Sequence[Record]],
        reflecting: Callable[[str, str], bool],
    ) -> None:
        """Consent from `gate`, decisions to `events`, steps from `session_records`.

        `reflecting(project, session_id)` says the session is answering the reflection ask.
        """
        self._gate = gate
        self._events = events
        self._records = session_records
        self._reflecting = reflecting
        self._holds: dict[SessionKey, int] = {}
        self._held_at: dict[SessionKey, int] = {}

    def decide(self, request: dict[str, Any]) -> dict[str, Any]:
        """`{"block": reason, "check": name}` to hold the stop, else `{"block": "", "why_not"}`.

        `reflecting` tells the hook whether this Stop ends the reflection turn.
        """
        project, key, host_active = _identified(request)
        reflecting = self._reflecting(project, key[1])
        reply = {**self._reply(project, key, reflecting=reflecting), "reflecting": reflecting}
        fields = {
            "asked": bool(reply["block"]),
            "why_not": reply.get("why_not", ""),
            "check": reply.get("check", ""),
            "host_stop_hook_active": host_active,
        }
        self._events.append_stop_guard(Call("stop/guard", STOP_HOOK, project), fields)
        return reply

    def _reply(self, project: str, key: SessionKey, *, reflecting: bool) -> dict[str, Any]:
        if not self._gate.door(project, STOP_HOOK).may_observe:
            return _skipped(f"symbiont is not switched on for {project}")
        if reflecting:
            return _skipped("this Stop ends the reflection turn")
        found = unfinished_check(self._records.get(key, ()))
        if found is None:
            return _skipped("no failed check is waiting for a passing re-run")
        if self._holds.get(key, 0) >= MAX_HOLDS:
            return _skipped(f"this session was already held {MAX_HOLDS} times")
        if found.step <= self._held_at.get(key, -1):
            return _skipped("no newer run of the failing check since the last hold")
        self._holds[key] = self._holds.get(key, 0) + 1
        self._held_at[key] = found.step
        return {"block": _reason(found), "check": found.check}


def _identified(request: dict[str, Any]) -> tuple[str, SessionKey, bool]:
    """The project, session key and `stop_hook_active` flag; anything malformed is a bad request."""
    require_keys(request, GUARD_KEYS, GUARD_REQUIRED)
    project, session_id, harness = (request[k] for k in ("project", "session_id", "harness"))
    active = request.get("stop_hook_active", False)
    if not (isinstance(project, str) and isinstance(harness, str)):
        raise BadRequestError("project and harness must be text")
    if not (isinstance(session_id, str) and session_id and isinstance(active, bool)):
        raise BadRequestError("session_id must be text and stop_hook_active true or false")
    return project, (harness, session_id), active


def _skipped(why_not: str) -> dict[str, Any]:
    """The reply for a Stop that is let through; the reason keeps silence from looking broken."""
    return {"block": "", "why_not": why_not}


def _reason(found: UnfinishedCheck) -> str:
    """The plain-prose reason the host shows the model; credentials never appear in it."""
    return scrub(
        f"The last run of `{found.check}` in this session failed ({found.excerpt}); "
        "the work is not done yet. Fix what it reports and run it again before you say the "
        "work is complete."
    )
