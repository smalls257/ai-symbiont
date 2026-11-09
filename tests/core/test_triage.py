"""The state a failure group is in now, from what the developer saved and what happened since.

Failure guarded against: a Resolved or Archived group that comes back and stays hidden (the
developer believes it is fixed while it recurs), or a Never archive that returns anyway.
"""

from datetime import date, timedelta

import pytest

from symbiont.core.triage import (
    GroupActivity,
    GroupState,
    ReturnRule,
    TriageRow,
    TriageShapeError,
    activity_since,
    got_worse,
    state_now,
    thirty_days_on,
    triage_row,
)

DAY = date(2026, 11, 6)


def saved(state, rule=None, after=None):
    return TriageRow(state, rule, after, DAY, None)


def test_a_group_nobody_triaged_is_for_review_and_not_regressed():
    assert state_now(None, GroupActivity(0, False), DAY) == (GroupState.FOR_REVIEW, False)
    assert state_now(None, GroupActivity(5, True), DAY) == (GroupState.FOR_REVIEW, False)


@pytest.mark.parametrize("state", [GroupState.FOR_REVIEW, GroupState.REVIEWED])
def test_for_review_and_reviewed_stay_as_saved_however_often_seen(state):
    assert state_now(saved(state), GroupActivity(9, True), DAY) == (state, False)


def test_resolved_stays_resolved_until_seen_in_a_new_session():
    assert state_now(saved(GroupState.RESOLVED), GroupActivity(0, False), DAY) == (
        GroupState.RESOLVED,
        False,
    )
    assert state_now(saved(GroupState.RESOLVED), GroupActivity(1, True), DAY) == (
        GroupState.FOR_REVIEW,
        True,
    )


def test_archived_new_session_returns_when_seen_in_a_new_session():
    row = saved(GroupState.ARCHIVED, ReturnRule.NEW_SESSION)

    assert state_now(row, GroupActivity(0, False), DAY) == (GroupState.ARCHIVED, False)
    assert state_now(row, GroupActivity(1, True), DAY) == (GroupState.FOR_REVIEW, True)


def test_archived_after_sessions_returns_at_exactly_the_count():
    row = saved(GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS, 3)

    assert state_now(row, GroupActivity(2, True), DAY) == (GroupState.ARCHIVED, False)
    assert state_now(row, GroupActivity(3, True), DAY) == (GroupState.FOR_REVIEW, True)
    assert state_now(row, GroupActivity(4, True), DAY) == (GroupState.FOR_REVIEW, True)


def test_archived_never_stays_archived_however_often_seen():
    row = saved(GroupState.ARCHIVED, ReturnRule.NEVER)

    assert state_now(row, GroupActivity(50, True), DAY) == (GroupState.ARCHIVED, False)


def test_an_archived_row_with_no_rule_raises_rather_than_guessing():
    with pytest.raises(TriageShapeError, match="return rule"):
        state_now(saved(GroupState.ARCHIVED), GroupActivity(1, True), DAY)


def test_group_activity_is_what_the_caller_measured_since_the_change():
    assert GroupActivity(2, True).sessions_since == 2


def test_triage_row_for_archived_needs_a_rule():
    with pytest.raises(TriageShapeError, match="return_rule"):
        triage_row(GroupState.ARCHIVED, None, None, DAY)


def test_triage_row_after_sessions_needs_a_positive_count():
    for bad in (None, 0, -1):
        with pytest.raises(TriageShapeError, match="after_sessions"):
            triage_row(GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS, bad, DAY)


def test_triage_row_refuses_a_rule_on_a_state_that_has_none():
    with pytest.raises(TriageShapeError, match="only an archived"):
        triage_row(GroupState.RESOLVED, ReturnRule.NEVER, None, DAY)


def test_triage_row_refuses_a_count_on_a_rule_that_has_none():
    with pytest.raises(TriageShapeError, match="after_sessions"):
        triage_row(GroupState.ARCHIVED, ReturnRule.NEW_SESSION, 2, DAY)


def test_triage_row_builds_each_valid_shape():
    assert triage_row(GroupState.REVIEWED, None, None, DAY) == saved(GroupState.REVIEWED)
    assert triage_row(GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS, 2, DAY) == saved(
        GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS, 2
    )


def test_an_after_sessions_row_with_no_count_raises():
    with pytest.raises(TriageShapeError, match="count"):
        state_now(
            saved(GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS), GroupActivity(1, True), DAY
        )


def test_activity_counts_distinct_sessions_dated_after_the_change_and_skips_undated_ones():
    cards = [
        ("old", date(2026, 11, 5)),
        ("same-day", DAY),
        ("later", date(2026, 11, 8)),
        ("later", date(2026, 11, 9)),
        ("other", date(2026, 11, 10)),
        ("undated", None),
    ]

    assert activity_since(DAY, cards, DAY, []) == GroupActivity(2, seen_in_new_session=True)


def test_a_group_with_nothing_after_the_change_has_no_activity():
    assert activity_since(DAY, [("a", DAY), ("b", None)], DAY, []) == GroupActivity(0, False)
    assert activity_since(DAY, [], DAY, []) == GroupActivity(0, False)


def days_from(start, count, step=1):
    return [start + timedelta(days=n * step) for n in range(count)]


def test_until_worse_returns_only_when_the_group_gets_worse():
    row = saved(GroupState.ARCHIVED, ReturnRule.UNTIL_WORSE)

    assert state_now(row, GroupActivity(5, True, got_worse=False), DAY) == (
        GroupState.ARCHIVED,
        False,
    )
    assert state_now(row, GroupActivity(1, True, got_worse=True), DAY) == (
        GroupState.FOR_REVIEW,
        True,
    )


def test_on_date_comes_back_on_the_day_and_not_a_day_before():
    until = date(2026, 12, 6)
    row = TriageRow(GroupState.ARCHIVED, ReturnRule.ON_DATE, None, DAY, None, until)

    assert state_now(row, GroupActivity(9, True), date(2026, 12, 5)) == (GroupState.ARCHIVED, False)
    assert state_now(row, GroupActivity(0, False), until) == (GroupState.FOR_REVIEW, True)
    assert state_now(row, GroupActivity(0, False), date(2027, 1, 1)) == (
        GroupState.FOR_REVIEW,
        True,
    )


def test_an_on_date_row_with_no_day_raises():
    row = TriageRow(GroupState.ARCHIVED, ReturnRule.ON_DATE, None, DAY, None)

    with pytest.raises(TriageShapeError, match="until"):
        state_now(row, GroupActivity(0, False), DAY)


def test_thirty_days_on_is_the_archive_day_plus_thirty():
    assert thirty_days_on(DAY) == date(2026, 12, 6)


def test_triage_row_on_date_needs_until_and_only_on_date_takes_one():
    with pytest.raises(TriageShapeError, match="until"):
        triage_row(GroupState.ARCHIVED, ReturnRule.ON_DATE, None, DAY)
    with pytest.raises(TriageShapeError, match="until"):
        triage_row(GroupState.ARCHIVED, ReturnRule.NEVER, None, DAY, date(2026, 12, 6))
    with pytest.raises(TriageShapeError, match="only an archived"):
        triage_row(GroupState.RESOLVED, None, None, DAY, date(2026, 12, 6))
    row = triage_row(GroupState.ARCHIVED, ReturnRule.ON_DATE, None, DAY, date(2026, 12, 6))
    assert row.until == date(2026, 12, 6)


def test_until_worse_row_takes_no_count():
    assert triage_row(GroupState.ARCHIVED, ReturnRule.UNTIL_WORSE, None, DAY).until is None
    with pytest.raises(TriageShapeError, match="after_sessions"):
        triage_row(GroupState.ARCHIVED, ReturnRule.UNTIL_WORSE, 3, DAY)


TODAY = date(2027, 1, 20)
ARCHIVED = date(2026, 12, 1)


def test_got_worse_when_the_recent_rate_is_over_one_and_a_half_times_the_earlier_one():
    sessions = days_from(date(2026, 10, 10), 10, 5) + days_from(ARCHIVED + timedelta(days=1), 20, 2)
    earlier = [date(2026, 10, 12), date(2026, 11, 20)]
    recent = days_from(ARCHIVED + timedelta(days=2), 10, 4)

    assert got_worse(ARCHIVED, TODAY, earlier + recent, sessions) is True


def test_a_steady_rate_is_not_worse():
    sessions = days_from(date(2026, 10, 10), 40, 3)
    seen = days_from(date(2026, 10, 11), 30, 4)

    assert got_worse(ARCHIVED, TODAY, seen, sessions) is False


def test_a_rise_below_the_floor_is_not_worse():
    sessions = days_from(date(2026, 10, 10), 200, 1)

    assert got_worse(ARCHIVED, TODAY, [TODAY - timedelta(days=3)], sessions) is False


def test_a_window_with_no_sessions_is_unknown_not_worse():
    seen = days_from(date(2027, 1, 1), 10)

    assert got_worse(ARCHIVED, TODAY, seen, days_from(date(2027, 1, 1), 10)) is False
    assert got_worse(ARCHIVED, TODAY, seen, days_from(date(2026, 11, 1), 10)) is False


def test_activity_since_carries_the_worse_verdict_for_the_given_today():
    sessions = days_from(date(2026, 10, 10), 10, 5) + days_from(ARCHIVED + timedelta(days=1), 20, 2)
    cards = [("a", date(2026, 10, 12))] + [
        (f"r{n}", day) for n, day in enumerate(days_from(ARCHIVED + timedelta(days=2), 10, 4))
    ]

    assert activity_since(ARCHIVED, cards, TODAY, sessions).got_worse is True
    assert activity_since(ARCHIVED, cards, ARCHIVED, sessions).got_worse is False
