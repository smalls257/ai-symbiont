"""The developer's review status of each failure group is kept, also across a re-mine.

Failure guarded against: a re-mine (which replaces mined tables) wiping what the developer
decided, so every Resolved group shows up as new work again.
"""

import sqlite3
from datetime import date

import pytest

from store_builders import save_lessons
from symbiont.core.triage import GroupState, ReturnRule, TriageRow, triage_row
from symbiont.store.held_back import REPLACED_TABLES
from symbiont.store.local import Store
from symbiont.store.triage import RuleTeach

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


def test_a_rename_is_kept_with_the_row_and_an_empty_name_restores_the_generated_one(store):
    store.review.triage.save("demo", "key-a", triage_row(GroupState.RESOLVED, None, None, DAY))

    store.review.triage.rename("demo", "key-a", "Flaky e2e login", DAY)
    store.review.triage.save("demo", "key-a", triage_row(GroupState.REVIEWED, None, None, LATER))

    assert store.review.triage.names("demo") == {"key-a": "Flaky e2e login"}
    store.review.triage.rename("demo", "key-a", "", LATER)
    assert store.review.triage.names("demo") == {}
    assert store.review.triage.all("demo")["key-a"].state is GroupState.REVIEWED


def test_naming_an_untriaged_group_leaves_it_for_review(store):
    store.review.triage.rename("demo", "key-b", "Docker build", DAY)

    assert store.review.triage.all("demo")["key-b"].state is GroupState.FOR_REVIEW


def test_a_renamed_group_keeps_its_name_after_a_re_mine(store):
    store.review.triage.rename("demo", "key-a", "Flaky e2e login", DAY)

    save_lessons(store, "demo", [], [], held_out_tasks=frozenset())

    assert store.review.triage.names("demo") == {"key-a": "Flaky e2e login"}


def test_a_store_from_before_names_gains_the_column_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    Store.open(path)
    db = sqlite3.connect(path)
    db.executescript(
        "DROP TABLE IF EXISTS triage;"
        "CREATE TABLE triage (project TEXT NOT NULL, group_key TEXT NOT NULL, state TEXT NOT NULL,"
        " return_rule TEXT, after_sessions INTEGER, changed_on TEXT NOT NULL, taught_on TEXT,"
        " PRIMARY KEY (project, group_key));"
        "INSERT INTO triage VALUES ('demo','k','resolved',NULL,NULL,'2026-11-06',NULL);"
    )
    db.close()

    reopened = Store.open(path)

    assert reopened.review.triage.all("demo")["k"].state is GroupState.RESOLVED
    assert reopened.review.triage.names("demo") == {}


def test_an_on_date_archive_round_trips_with_its_day(store):
    row = triage_row(GroupState.ARCHIVED, ReturnRule.ON_DATE, None, DAY, date(2026, 12, 6))

    store.review.triage.save("demo", "key-a", row)

    assert store.review.triage.all("demo") == {"key-a": row}
    assert row.until == date(2026, 12, 6)


def test_an_until_worse_archive_round_trips_and_a_later_save_clears_the_day(store):
    store.review.triage.save(
        "demo", "key-a", triage_row(GroupState.ARCHIVED, ReturnRule.ON_DATE, None, DAY, LATER)
    )
    worse = triage_row(GroupState.ARCHIVED, ReturnRule.UNTIL_WORSE, None, LATER)

    store.review.triage.save("demo", "key-a", worse)

    assert store.review.triage.all("demo")["key-a"] == worse


def test_a_store_from_before_for_30_days_gains_the_until_column(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE triage (project TEXT NOT NULL, group_key TEXT NOT NULL, state TEXT NOT NULL,"
        " return_rule TEXT, after_sessions INTEGER, changed_on TEXT NOT NULL, taught_on TEXT,"
        " name TEXT NOT NULL DEFAULT '', PRIMARY KEY (project, group_key))"
    )
    db.execute(
        "INSERT INTO triage VALUES ('demo', 'k', 'archived', 'never', NULL, '2026-11-06', NULL, '')"
    )
    db.commit()
    db.close()

    store = Store.open(path)

    assert store.review.triage.all("demo")["k"].until is None


def test_the_id_of_the_lesson_a_group_was_taught_is_kept_and_absent_when_none_was_sent(store):
    store.review.triage.mark_taught("demo", "key-a", DAY, "lesson-1")
    store.review.triage.mark_taught("demo", "key-b", DAY)

    assert store.review.triage.lesson_ids("demo") == {"key-a": "lesson-1"}


def test_teaching_again_updates_the_id_and_a_teach_without_one_keeps_it(store):
    store.review.triage.mark_taught("demo", "key-a", DAY, "lesson-1")
    store.review.triage.mark_taught("demo", "key-a", LATER, "lesson-2")
    store.review.triage.mark_taught("demo", "key-a", LATER)

    assert store.review.triage.lesson_ids("demo") == {"key-a": "lesson-2"}


def test_a_store_from_before_lesson_ids_opens_reads_none_and_takes_a_teach(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE triage (project TEXT NOT NULL, group_key TEXT NOT NULL, state TEXT NOT NULL,"
        " return_rule TEXT, after_sessions INTEGER, changed_on TEXT NOT NULL, taught_on TEXT,"
        " name TEXT NOT NULL DEFAULT '', until TEXT, PRIMARY KEY (project, group_key))"
    )
    db.execute(
        "INSERT INTO triage VALUES ('demo', 'k', 'reviewed', NULL, NULL, '2026-11-06',"
        " '2026-11-06', '', NULL)"
    )
    db.commit()
    db.close()

    store = Store.open(path)
    assert store.review.triage.lesson_ids("demo") == {}
    store.review.triage.mark_taught("demo", "k", DAY, "lesson-1")

    assert store.review.triage.lesson_ids("demo") == {"k": "lesson-1"}
    columns = {c[1] for c in sqlite3.connect(path).execute("PRAGMA table_info(triage)")}
    assert "lesson" not in columns


def test_a_rule_teach_keeps_its_messages_with_the_taught_day(tmp_path):
    store = Store.open(tmp_path / "s.db")
    store.review.triage.mark_rule_taught(
        "demo", "rule:a:1", RuleTeach(DAY, "l1", (("a", 1), ("b", 2)))
    )
    assert store.review.triage.members_by_key("demo") == {"rule:a:1": {("a", 1), ("b", 2)}}
    assert store.review.triage.lesson_ids("demo") == {"rule:a:1": "l1"}
