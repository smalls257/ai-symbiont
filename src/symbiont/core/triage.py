"""The review status of a failure group: For review, Reviewed, Resolved, Archived.

A group the developer called Resolved or Archived that comes back must not stay hidden: it
returns to For review marked Regressed (the Sentry and Datadog issue lifecycle). Pure: dates
and session counts come in, no clock is read.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from symbiont.core.trends import RISING_FACTOR, RISING_FLOOR_PER_10, rate_per_10

# "For 30 days" in the archive menu (mockup v3): the day it comes back is the archive day plus this.
ON_DATE_DAYS = 30
# "Until it gets worse" compares eight weeks with eight weeks (mockup v3 text); the factor and
# floor are the Trends badge's own, so a group that reads "rising" there comes back here.
WORSE_WINDOW_DAYS = 56


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
    UNTIL_WORSE = "until_worse"
    ON_DATE = "on_date"
    NEVER = "never"


class TriageShapeError(ValueError):
    """A triage state that does not fit its rule (for example Archived with no return rule)."""


@dataclass(frozen=True)
class TriageRow:
    """What the developer saved for one group.

    `changed_on` is the day the state was set; `taught_on` the day "Teach the agent" was used;
    `until` the day an ON_DATE archive comes back.
    """

    state: GroupState
    return_rule: ReturnRule | None
    after_sessions: int | None
    changed_on: date
    taught_on: date | None
    until: date | None = None


@dataclass(frozen=True)
class GroupActivity:
    """What happened to a group after `TriageRow.changed_on`, measured by the caller.

    `sessions_since` is the number of sessions after that day in which the group was seen
    again; `seen_in_new_session` is whether that number is above zero; `got_worse` is whether its
    rate over the last eight weeks is well above its rate over the eight weeks before the change.
    """

    sessions_since: int
    seen_in_new_session: bool
    got_worse: bool = False


def activity_since(
    changed_on: date,
    card_days: Iterable[tuple[str, date | None]],
    today: date,
    session_days: Sequence[date],
) -> GroupActivity:
    """Cards as (session id, day) pairs to activity; undated cards never count as later.

    `session_days` is one day per project session, the denominator of the worse-rate.
    """
    cards = list(card_days)
    later = {session for session, day in cards if day is not None and day > changed_on}
    days = [day for _, day in cards if day is not None]
    return GroupActivity(len(later), bool(later), got_worse(changed_on, today, days, session_days))


def got_worse(
    changed_on: date, today: date, occurrence_days: Sequence[date], session_days: Sequence[date]
) -> bool:
    """Whether the last eight weeks' rate per session beats the eight weeks before `changed_on`.

    A window with no sessions has no rate, so it never counts as worse.
    """
    span = timedelta(days=WORSE_WINDOW_DAYS)
    now = _window_rate(today - span, today, occurrence_days, session_days)
    before = _window_rate(changed_on - span, changed_on, occurrence_days, session_days)
    if now is None or before is None:
        return False
    return now > RISING_FACTOR * before and now > RISING_FLOOR_PER_10


def _window_rate(
    start: date, end: date, occurrence_days: Sequence[date], session_days: Sequence[date]
) -> float | None:
    """Occurrences per 10 sessions on the days after `start` up to and including `end`."""
    times = sum(1 for day in occurrence_days if start < day <= end)
    return rate_per_10(times, sum(1 for day in session_days if start < day <= end))


def thirty_days_on(changed_on: date) -> date:
    """The day a "For 30 days" archive made on `changed_on` comes back."""
    return changed_on + timedelta(days=ON_DATE_DAYS)


def triage_row(
    state: GroupState,
    rule: ReturnRule | None,
    after_sessions: int | None,
    changed_on: date,
    until: date | None = None,
) -> TriageRow:
    """A row that fits its rule; raises TriageShapeError naming what does not.

    Only Archived carries a return rule; only AFTER_SESSIONS carries a positive count and only
    ON_DATE carries `until`.
    """
    if state is not GroupState.ARCHIVED:
        if rule is not None or after_sessions is not None or until is not None:
            raise TriageShapeError("only an archived group carries a return rule")
        return TriageRow(state, None, None, changed_on, None)
    if rule is None:
        raise TriageShapeError("an archived group needs a return_rule")
    _check_rule_fields(rule, after_sessions, until)
    return TriageRow(state, rule, after_sessions, changed_on, None, until)


def _check_rule_fields(rule: ReturnRule, after_sessions: int | None, until: date | None) -> None:
    """Raises TriageShapeError unless the count and day are exactly the ones `rule` carries."""
    if rule is ReturnRule.AFTER_SESSIONS:
        if after_sessions is None or after_sessions < 1:
            raise TriageShapeError("after_sessions must be a whole number of 1 or more")
    elif after_sessions is not None:
        raise TriageShapeError(f"after_sessions belongs to {ReturnRule.AFTER_SESSIONS.value} only")
    if rule is ReturnRule.ON_DATE and until is None:
        raise TriageShapeError(f"{ReturnRule.ON_DATE.value} needs an until day")
    if rule is not ReturnRule.ON_DATE and until is not None:
        raise TriageShapeError(f"until belongs to {ReturnRule.ON_DATE.value} only")


def state_now(
    saved: TriageRow | None, activity: GroupActivity, today: date
) -> tuple[GroupState, bool]:
    """The state on `today` and whether it regressed; `activity` is measured since `changed_on`.

    Raises TriageShapeError for an Archived row whose rule lacks its count or day.
    """
    if saved is None:
        return GroupState.FOR_REVIEW, False
    if saved.state is GroupState.RESOLVED and activity.seen_in_new_session:
        return GroupState.FOR_REVIEW, True
    if saved.state is GroupState.ARCHIVED and _archive_is_due(saved, activity, today):
        return GroupState.FOR_REVIEW, True
    return saved.state, False


def _archive_is_due(saved: TriageRow, activity: GroupActivity, today: date) -> bool:
    """Whether an archived group's own return rule says it comes back now."""
    rule = saved.return_rule
    if rule is ReturnRule.NEW_SESSION:
        return activity.seen_in_new_session
    if rule is ReturnRule.UNTIL_WORSE:
        return activity.got_worse
    if rule is ReturnRule.NEVER:
        return False
    if rule is ReturnRule.AFTER_SESSIONS:
        if saved.after_sessions is None:
            raise TriageShapeError("an after_sessions rule has no count")
        return activity.sessions_since >= saved.after_sessions
    if rule is ReturnRule.ON_DATE:
        if saved.until is None:
            raise TriageShapeError("an on_date rule has no until day")
        return today >= saved.until
    raise TriageShapeError("an archived group has no return rule")
