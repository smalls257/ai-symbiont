"""The state a failure group is in now, from what the developer saved and what happened since.

Failure guarded against: a Resolved or Archived group that comes back and stays hidden (the
developer believes it is fixed while it recurs), or a Never archive that returns anyway.
"""

from datetime import date

import pytest

from symbiont.core.triage import (
    GroupActivity,
    GroupState,
    ReturnRule,
    TriageRow,
    TriageShapeError,
    activity_since,
    state_now,
    triage_row,
)

DAY = date(2026, 11, 6)


def saved(state, rule=None, after=None):
    return TriageRow(state, rule, after, DAY, None)


def test_a_group_nobody_triaged_is_for_review_and_not_regressed():
    assert state_now(None, 0, seen_in_new_session=False) == (GroupState.FOR_REVIEW, False)
    assert state_now(None, 5, seen_in_new_session=True) == (GroupState.FOR_REVIEW, False)


@pytest.mark.parametrize("state", [GroupState.FOR_REVIEW, GroupState.REVIEWED])
def test_for_review_and_reviewed_stay_as_saved_however_often_seen(state):
    assert state_now(saved(state), 9, seen_in_new_session=True) == (state, False)


def test_resolved_stays_resolved_until_seen_in_a_new_session():
    assert state_now(saved(GroupState.RESOLVED), 0, seen_in_new_session=False) == (
        GroupState.RESOLVED,
        False,
    )
    assert state_now(saved(GroupState.RESOLVED), 1, seen_in_new_session=True) == (
        GroupState.FOR_REVIEW,
        True,
    )


def test_archived_new_session_returns_when_seen_in_a_new_session():
    row = saved(GroupState.ARCHIVED, ReturnRule.NEW_SESSION)

    assert state_now(row, 0, seen_in_new_session=False) == (GroupState.ARCHIVED, False)
    assert state_now(row, 1, seen_in_new_session=True) == (GroupState.FOR_REVIEW, True)


def test_archived_after_sessions_returns_at_exactly_the_count():
    row = saved(GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS, 3)

    assert state_now(row, 2, seen_in_new_session=True) == (GroupState.ARCHIVED, False)
    assert state_now(row, 3, seen_in_new_session=True) == (GroupState.FOR_REVIEW, True)
    assert state_now(row, 4, seen_in_new_session=True) == (GroupState.FOR_REVIEW, True)


def test_archived_never_stays_archived_however_often_seen():
    row = saved(GroupState.ARCHIVED, ReturnRule.NEVER)

    assert state_now(row, 50, seen_in_new_session=True) == (GroupState.ARCHIVED, False)


def test_an_archived_row_with_no_rule_raises_rather_than_guessing():
    with pytest.raises(TriageShapeError, match="return rule"):
        state_now(saved(GroupState.ARCHIVED), 1, seen_in_new_session=True)


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
            saved(GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS), 1, seen_in_new_session=True
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

    assert activity_since(DAY, cards) == GroupActivity(2, seen_in_new_session=True)


def test_a_group_with_nothing_after_the_change_has_no_activity():
    assert activity_since(DAY, [("a", DAY), ("b", None)]) == GroupActivity(0, False)
    assert activity_since(DAY, []) == GroupActivity(0, False)
