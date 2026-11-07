"""The developer's review status of each failure group is kept, also across a re-mine.

Failure guarded against: a re-mine (which replaces mined tables) wiping what the developer
decided, so every Resolved group shows up as new work again.
"""

from datetime import date

import pytest

from store_builders import save_lessons
from symbiont.core.triage import GroupState, ReturnRule, TriageRow, triage_row
from symbiont.store.held_back import REPLACED_TABLES
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery

DAY = date(2026, 11, 6)
LATER = date(2026, 11, 9)


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / "store.db")


def test_nothing_is_saved_for_a_new_project(store):
    assert store.review.triage.all("demo") == {}


def test_a_saved_state_reads_back_exactly(store):
    row = triage_row(GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS, 3, DAY)

    store.review.triage.save("demo", "key-a", row)

    assert store.review.triage.all("demo") == {"key-a": row}


def test_saving_again_replaces_the_state_and_keeps_the_taught_day(store):
    store.review.triage.save("demo", "key-a", triage_row(GroupState.REVIEWED, None, None, DAY))
    store.review.triage.mark_taught("demo", "key-a", DAY)

    store.review.triage.save("demo", "key-a", triage_row(GroupState.RESOLVED, None, None, LATER))

    assert store.review.triage.all("demo")["key-a"] == TriageRow(
        GroupState.RESOLVED, None, None, LATER, DAY
    )


def test_teaching_a_group_nobody_triaged_leaves_it_for_review(store):
    store.review.triage.mark_taught("demo", "key-b", DAY)

    assert store.review.triage.all("demo")["key-b"] == TriageRow(
        GroupState.FOR_REVIEW, None, None, DAY, DAY
    )


def test_projects_do_not_share_triage(store):
    store.review.triage.save("demo", "key-a", triage_row(GroupState.REVIEWED, None, None, DAY))

    assert store.review.triage.all("other") == {}


def test_triage_is_not_a_replaced_table():
    assert "triage" not in REPLACED_TABLES


def test_a_remine_keeps_triage_rows(store):
    row = triage_row(GroupState.RESOLVED, None, None, DAY)
    store.review.triage.save("demo", "key-a", row)

    save_lessons(store, "demo", [], [], held_out_tasks=frozenset())

    assert store.review.triage.all("demo") == {"key-a": row}
