"""A session's date comes from the session; one without a date is unknown, never today."""

from dataclasses import replace
from datetime import date

import pytest

from record_builders import edit, run, session
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.session_dates import order_sessions, undated_count

pytestmark = pytest.mark.periphery
TODAY = date(2026, 11, 6)
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"


def lessons_in(*session_ids):
    steps = []
    for sid in session_ids:
        steps += [
            replace(step, project="demo", session_id=sid)
            for step in session(
                run("pytest tests/test_parser.py", 1, IMPORT),
                edit("app/parser.py", diff="-a\n+def parse(text):\n"),
                run("pytest tests/test_parser.py", 0, "1 passed"),
            )
        ]
    return lessons_from(mine_history(sessions_of(steps), {}), steps, frozenset())


def test_a_session_without_a_date_is_null_not_today():
    view = RepoView("demo", lessons_in("a", "b"), {}, {"a": date(2026, 10, 3)})

    data = dashboard_snapshot(view, TODAY)

    by_index = {s["index"]: s for s in data["sessions"]}
    assert sorted(s["date"] for s in data["sessions"] if s["date"]) == ["2026-10-03"]
    assert [s["date"] for s in data["sessions"]].count(None) == 1
    assert "2026-11-06" not in str(data["sessions"])
    assert all(s["day"] is None for s in data["sessions"] if s["date"] is None)
    assert by_index[0]["date"] == "2026-10-03"  # dated sessions come first, oldest first


def test_replay_counts_sessions_it_cannot_place():
    view = RepoView("demo", lessons_in("a", "b", "c"), {}, {"a": date(2026, 10, 3)})

    replay = dashboard_snapshot(view, TODAY)["replay"]

    assert replay["undated"] == 2
    assert replay["items"] == []


def test_a_fully_undated_repository_has_no_dates_and_no_replay_items():
    data = dashboard_snapshot(RepoView("demo", lessons_in("a", "b"), {}, {}), TODAY)

    assert [s["date"] for s in data["sessions"]] == [None, None]
    assert data["replay"]["items"] == [] and data["replay"]["undated"] == 2


def test_ordering_puts_undated_sessions_after_dated_ones_in_first_seen_order():
    dates = {"d1": date(2026, 1, 1), "d2": date(2026, 2, 1)}
    order = order_sessions(["u1", "d2", "u2", "d1"], dates)

    assert [(sid, index) for sid, (index, _) in order.items()] == [
        ("d1", 0),
        ("d2", 1),
        ("u1", 2),
        ("u2", 3),
    ]
    assert undated_count(order) == 2


def test_sessions_are_dated_from_their_start_day_and_never_from_a_log_file():
    from symbiont.miner.struggle import SessionFacts
    from symbiont.service.session_dates import session_dates_of

    def fact(sid, started):
        return SessionFacts(sid, sid, frozenset(), frozenset(), 0, {}, False, started)

    facts = [fact("dated", "2026-03-02"), fact("undated", None)]

    assert session_dates_of(facts) == {"dated": date(2026, 3, 2)}


def test_a_written_lesson_sits_on_the_newest_dated_session_not_an_undated_one():
    from symbiont.miner.lesson_context import AuthoredLesson, LessonKind

    written = [AuthoredLesson("w1", "Refunds never retry.", LessonKind.RULE, ())]
    view = RepoView("demo", lessons_in("u", "d"), {}, {"d": date(2026, 10, 3)}, written=written)

    data = dashboard_snapshot(view, TODAY)

    dated_index = next(s["index"] for s in data["sessions"] if s["date"])
    written_point = next(p for p in data["painPoints"] if p["lessonId"] == "w1")
    assert written_point["sessions"] == [dated_index]
