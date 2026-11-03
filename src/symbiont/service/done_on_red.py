"""The done-on-red guard: a Stop is blocked once when the session's last run of a check failed.

`miner/unfinished_check.py` reads the session's records; the Stop hook is a thin client. Every
decision, asked or skipped, is an event with its reason. It never loops: a Stop the host already
continued is not blocked, a session is blocked at most once, and the Stop after a block is handed
on to the reflection ask (`after_guard`).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from symbiont.miner.credential_scrub import scrub
from symbiont.miner.unfinished_check import UnfinishedCheck, unfinished_check
from symbiont.records.schema import Record
from symbiont.service.events import Call, EventLog
from symbiont.service.repo_gate import RepoGate
from symbiont.service.request_shapes import BadRequestError, require_keys

GUARD_REQUIRED = frozenset({"project", "session_id", "harness"})
GUARD_KEYS = GUARD_REQUIRED | {"stop_hook_active"}
STOP_HOOK = "Stop"
SessionKey = tuple[str, str]  # (harness, session id), as the service keys its records


class DoneOnRedGuard:
    """Decides, per Stop, whether to block because a check is still red; remembers it did."""

    def __init__(
        self,
        gate: RepoGate,
        events: EventLog,
        session_records: Mapping[SessionKey, Sequence[Record]],
    ) -> None:
        """Consent from `gate`, decisions to `events`, steps from `session_records`."""
        self._gate = gate
        self._events = events
        self._records = session_records
        self._blocked: set[SessionKey] = set()
        self._handed_on: set[SessionKey] = set()

    def decide(self, request: dict[str, Any]) -> dict[str, Any]:
        """`{"block": reason, "check": name}` to hold the stop, else `{"block": "", "why_not"}`.

        `after_guard` is true on the one Stop that follows a block this guard asked for.
        """
        project, key, active = _identified(request)
        reply = self._reply(project, key, active=active)
        fields = {
            "asked": bool(reply["block"]),
            "why_not": reply.get("why_not", ""),
            "check": reply.get("check", ""),
        }
        self._events.append_stop_guard(Call("stop/guard", STOP_HOOK, project), fields)
        return reply

    def _reply(self, project: str, key: SessionKey, *, active: bool) -> dict[str, Any]:
        if not self._gate.door(project, STOP_HOOK).may_observe:
            return _skipped(f"symbiont is not switched on for {project}")
        if active:
            return self._continued_stop(key)
        if key in self._blocked:
            return _skipped("this session was already held once for a failing check")
        found = unfinished_check(self._records.get(key, ()))
        if found is None:
            return _skipped("no failed check is waiting for a passing re-run")
        self._blocked.add(key)
        return {"block": _reason(found), "check": found.check}

    def _continued_stop(self, key: SessionKey) -> dict[str, Any]:
        """A Stop the host already continued: never blocked; ours hands on to the reflection."""
        if key in self._blocked and key not in self._handed_on:
            self._handed_on.add(key)
            return _skipped("stop_hook_active after the guard's own block", after_guard=True)
        return _skipped("stop_hook_active: this Stop already continues a hook's block")


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


def _skipped(why_not: str, *, after_guard: bool = False) -> dict[str, Any]:
    """The reply for a Stop that is let through; the reason keeps silence from looking broken."""
    return {"block": "", "why_not": why_not, "after_guard": after_guard}


def _reason(found: UnfinishedCheck) -> str:
    """The plain-prose reason the host shows the model; credentials never appear in it."""
    return scrub(
        f"The last run of `{found.check}` in this session failed ({found.excerpt}); "
        "the work is not done yet. Fix what it reports and run it again before you say the "
        "work is complete."
    )
