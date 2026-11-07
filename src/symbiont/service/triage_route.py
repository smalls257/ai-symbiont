"""POST /triage: the developer's review status of a failure group, and "Teach the agent".

The caller names a state and, for
Archived, a return rule; a shape that does not fit is a 400 naming the field, never a guess.
`group_key` is the group's opaque fingerprint and is kept as text. Dates come from the service.
"""

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING, Any

from symbiont.core.triage import (
    GroupActivity,
    GroupState,
    ReturnRule,
    TriageRow,
    TriageShapeError,
    state_now,
    triage_row,
)
from symbiont.service.events import Call, write_event
from symbiont.service.request_shapes import BadRequestError, consented_project, require_keys
from symbiont.store.local import Store

if TYPE_CHECKING:
    from symbiont.service.app import ServiceParts

TRIAGE_KEYS = frozenset(
    {"project", "group_key", "state", "return_rule", "after_sessions", "taught"}
)
TRIAGE_REQUIRED = frozenset({"project", "group_key"})
NO_ACTIVITY = GroupActivity(0, seen_in_new_session=False)


def save_triage(parts: "ServiceParts", request: dict[str, Any], today: date) -> dict[str, Any]:
    """Set a group's state (with its return rule) and/or record that it was taught, today.

    Raises BadRequestError for a repository nobody allowed, an unknown state or rule, a state
    that needs a field it lacks, or a request that changes nothing.
    """
    require_keys(request, TRIAGE_KEYS, TRIAGE_REQUIRED)
    store = parts.store
    project = consented_project(parts.gate.registry, request)
    key = request["group_key"]
    if not isinstance(key, str) or not key:
        raise BadRequestError("group_key must be text")
    taught = request.get("taught", False)
    if taught is not True and (taught is not False or "state" not in request):
        raise BadRequestError("send a state, or taught: true")
    if "state" in request:
        store.review.triage.save(project, key, _row_of(request, today))
    if taught:
        store.review.triage.mark_taught(project, key, today)
    saved = store.review.triage.all(project)[key]
    reply = {"group_key": key, "state": saved.state.value, "taught_on": _day(saved.taught_on)}
    events = parts.events
    write_event(events.path, events.filler, Call("triage", "triage", project), {"triage": reply})
    return reply


def triage_listing(
    store: Store, project: str, activity: Mapping[str, GroupActivity] | None = None
) -> dict[str, dict[str, Any]]:
    """The snapshot's `triage`: group key -> state now, regressed, taught_on.

    `activity` is what the caller measured per group since its saved day; a group it does not
    mention counts as not seen again.
    """
    seen = activity or {}
    listing: dict[str, dict[str, Any]] = {}
    for key, row in store.review.triage.all(project).items():
        now = seen.get(key, NO_ACTIVITY)
        state, regressed = state_now(
            row, now.sessions_since, seen_in_new_session=now.seen_in_new_session
        )
        listing[key] = {
            "state": state.value,
            "regressed": regressed,
            "taught_on": _day(row.taught_on),
        }
    return listing


def _day(day: date | None) -> str | None:
    """A date as ISO text, or None."""
    return None if day is None else day.isoformat()


def _row_of(request: dict[str, Any], today: date) -> TriageRow:
    """The row a request describes, or BadRequestError naming what does not fit."""
    state = _enum(GroupState, "state", request["state"])
    rule = request.get("return_rule")
    after = request.get("after_sessions")
    if after is not None and (isinstance(after, bool) or not isinstance(after, int)):
        raise BadRequestError("after_sessions must be a whole number")
    try:
        return triage_row(
            state, None if rule is None else _enum(ReturnRule, "return_rule", rule), after, today
        )
    except TriageShapeError as exc:
        raise BadRequestError(str(exc)) from exc


def _enum[E: (GroupState, ReturnRule)](kind: type[E], field: str, value: object) -> E:
    """The member of `kind` that `value` names, or BadRequestError listing the choices."""
    try:
        return kind(value)
    except ValueError as exc:
        choices = ", ".join(member.value for member in kind)
        raise BadRequestError(f"unknown {field} {value!r}; choose one of {choices}") from exc
