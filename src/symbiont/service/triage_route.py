"""POST /triage: the developer's review status of a failure group, and "Teach the agent".

The caller names a state and, for
Archived, a return rule; a shape that does not fit is a 400 naming the field, never a guess.
`group_key` is the group's opaque fingerprint and is kept as text. Dates come from the service.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import TYPE_CHECKING, Any

from symbiont.core.triage import (
    GroupActivity,
    GroupState,
    ReturnRule,
    TriageRow,
    TriageShapeError,
    activity_since,
    state_now,
    thirty_days_on,
    triage_row,
)
from symbiont.miner.credential_patterns import scrub
from symbiont.service.events import Call, write_event
from symbiont.service.request_shapes import (
    BadRequestError,
    consented_project,
    display_name,
    require_keys,
)
from symbiont.store.local import Store

if TYPE_CHECKING:
    from symbiont.service.app import ServiceParts

TRIAGE_KEYS = frozenset(
    {"project", "group_key", "state", "return_rule", "after_sessions", "taught", "name", "lesson"}
)
TRIAGE_REQUIRED = frozenset({"project", "group_key"})
# The Trends panel shows the words in one line of a side column; a longer lesson is cut.
MAX_LESSON_CHARS = 600
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
    named = "name" in request
    if taught is not True and (taught is not False or ("state" not in request and not named)):
        raise BadRequestError("send a state, a name, or taught: true")
    name = display_name(request["name"]) if named else ""
    row = _row_of(request, today) if "state" in request else None
    if named:
        store.review.triage.rename(project, key, name, today)
    if row is not None:
        store.review.triage.save(project, key, row)
    if taught:
        store.review.triage.mark_taught(project, key, today, _lesson_words(request))
    saved = store.review.triage.all(project)[key]
    reply = {
        "group_key": key,
        "state": saved.state.value,
        "taught_on": _day(saved.taught_on),
        "name": store.review.triage.names(project).get(key, ""),
    }
    events = parts.events
    write_event(events.path, events.filler, Call("triage", "triage", project), {"triage": reply})
    return reply


def _lesson_words(request: dict[str, Any]) -> str:
    """The lesson text sent with `taught`, scrubbed and capped; "" when none was sent."""
    words = request.get("lesson", "")
    if not isinstance(words, str):
        raise BadRequestError("lesson must be text")
    return scrub(words.strip())[:MAX_LESSON_CHARS]


def triage_listing(
    store: Store, project: str, today: date, activity: Mapping[str, GroupActivity] | None = None
) -> dict[str, dict[str, Any]]:
    """The snapshot's `triage` on `today`: group key -> state, regressed, taught_on, name.

    `activity` is what the caller measured per group since its saved day; a group it does not
    mention counts as not seen again.
    """
    seen = activity or {}
    names = store.review.triage.names(project)
    listing: dict[str, dict[str, Any]] = {}
    for key, row in store.review.triage.all(project).items():
        now = seen.get(key, NO_ACTIVITY)
        state, regressed = state_now(row, now, today)
        listing[key] = {
            "state": state.value,
            "regressed": regressed,
            "taught_on": _day(row.taught_on),
            "name": names.get(key, ""),
        }
    return listing


def group_activity(
    store: Store,
    project: str,
    groups: Sequence[Mapping[str, Any]],
    when: tuple[date, Sequence[date]],
) -> dict[str, GroupActivity]:
    """For each triaged group, the sessions that showed it after its state was set.

    `groups` are the incident groups of the page's data (each with `key` and `cards`, a card
    being a `sessionId` and an ISO `date` or None). `when` is today and one day per session of
    the project (the rates' denominator). Groups nobody triaged have no entry.
    """
    today, session_days = when
    rows = store.review.triage.all(project)
    return {
        group["key"]: activity_since(
            rows[group["key"]].changed_on,
            [(c["sessionId"], _date_of(c["date"])) for c in group["cards"]],
            today,
            session_days,
        )
        for group in groups
        if group["key"] in rows
    }


def _date_of(text: str | None) -> date | None:
    return None if text is None else date.fromisoformat(text)


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
    rule = None if rule is None else _enum(ReturnRule, "return_rule", rule)
    until = thirty_days_on(today) if rule is ReturnRule.ON_DATE else None
    try:
        return triage_row(state, rule, after, today, until)
    except TriageShapeError as exc:
        raise BadRequestError(str(exc)) from exc


def _enum[E: (GroupState, ReturnRule)](kind: type[E], field: str, value: object) -> E:
    """The member of `kind` that `value` names, or BadRequestError listing the choices."""
    choices = ", ".join(member.value for member in kind)
    if not isinstance(value, str):
        raise BadRequestError(f"{field} must be text; choose one of {choices}")
    try:
        return kind(value)
    except ValueError as exc:
        raise BadRequestError(f"unknown {field} {value!r}; choose one of {choices}") from exc
