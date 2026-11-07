"""The review status of a failure group: For review, Reviewed, Resolved, Archived.

A group the developer called Resolved or Archived that comes back must not stay hidden: it
returns to For review marked Regressed (the Sentry and Datadog issue lifecycle). Pure: dates
and session counts come in, no clock is read.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class GroupState(StrEnum):
    """Where a failure group stands in the developer's review."""

    FOR_REVIEW = "for_review"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class ReturnRule(StrEnum):
    """When an archived group comes back to For review."""

    NEW_SESSION = "new_session"
    AFTER_SESSIONS = "after_sessions"
    NEVER = "never"


class TriageShapeError(ValueError):
    """A triage state that does not fit its rule (for example Archived with no return rule)."""


@dataclass(frozen=True)
class TriageRow:
    """What the developer saved for one group.

    `changed_on` is the day the state was set; `taught_on` the day "Teach the agent" was used.
    """

    state: GroupState
    return_rule: ReturnRule | None
    after_sessions: int | None
    changed_on: date
    taught_on: date | None


@dataclass(frozen=True)
class GroupActivity:
    """What happened to a group after `TriageRow.changed_on`, measured by the caller.

    `sessions_since` is the number of sessions after that day in which the group was seen
    again; `seen_in_new_session` is whether that number is above zero.
    """

    sessions_since: int
    seen_in_new_session: bool


def triage_row(
    state: GroupState, rule: ReturnRule | None, after_sessions: int | None, changed_on: date
) -> TriageRow:
    """A row that fits its rule; raises TriageShapeError naming what does not.

    Only Archived carries a return rule, and only AFTER_SESSIONS carries a positive count.
    """
    if state is not GroupState.ARCHIVED:
        if rule is not None or after_sessions is not None:
            raise TriageShapeError("only an archived group carries a return rule")
        return TriageRow(state, None, None, changed_on, None)
    if rule is None:
        raise TriageShapeError("an archived group needs a return_rule")
    if rule is ReturnRule.AFTER_SESSIONS:
        if after_sessions is None or after_sessions < 1:
            raise TriageShapeError("after_sessions must be a whole number of 1 or more")
    elif after_sessions is not None:
        raise TriageShapeError(f"after_sessions belongs to {ReturnRule.AFTER_SESSIONS.value} only")
    return TriageRow(state, rule, after_sessions, changed_on, None)


def state_now(
    saved: TriageRow | None, sessions_since: int, *, seen_in_new_session: bool
) -> tuple[GroupState, bool]:
    """The state now and whether it regressed; inputs are `GroupActivity` since `changed_on`.

    Raises TriageShapeError for an Archived row with no return rule.
    """
    if saved is None:
        return GroupState.FOR_REVIEW, False
    if saved.state is GroupState.RESOLVED and seen_in_new_session:
        return GroupState.FOR_REVIEW, True
    archived = saved.state is GroupState.ARCHIVED
    if archived and _archive_is_due(saved, sessions_since, seen=seen_in_new_session):
        return GroupState.FOR_REVIEW, True
    return saved.state, False


def _archive_is_due(saved: TriageRow, sessions_since: int, *, seen: bool) -> bool:
    """Whether an archived group's own return rule says it comes back now."""
    if saved.return_rule is ReturnRule.NEW_SESSION:
        return seen
    if saved.return_rule is ReturnRule.AFTER_SESSIONS:
        if saved.after_sessions is None:
            raise TriageShapeError("an after_sessions rule has no count")
        return sessions_since >= saved.after_sessions
    if saved.return_rule is ReturnRule.NEVER:
        return False
    raise TriageShapeError("an archived group has no return rule")
