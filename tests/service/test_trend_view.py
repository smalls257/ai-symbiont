"""The `trends` data: rates per 10 sessions by month, a trend word, before/after, undated left out.

Failure guarded against: undated sessions or cards read as a month's zero, a taught group with
no before/after, and a one-off or noise group cluttering the view.
"""

from datetime import date

import pytest

from quiet_store import mine_a_session_without_failures
from symbiont.miner.lesson_context import AuthoredLesson, LessonKind
from symbiont.service.trend_view import Taught, taught_lessons, trends_of, trends_snapshot
from symbiont.store.local import Store


def group(key, dates, *, recurring=True, noise=None):
    last = max((d for d in dates if d), default=None)
    return {
        "key": key, "name": f"{key} failing", "title": f"raw command of {key}",
        "kind": "failure", "last": last,
        "recurring": recurring, "noise": noise,
        "cards": [{"date": d, "sessionId": f"{key}-{i}"} for i, d in enumerate(dates)],
    }  # fmt: skip


def sessions(month, count):
    return [date(2026, month, 1 + i) for i in range(count)]


def test_each_month_has_a_rate_per_ten_sessions_and_the_months_say_how_many_sessions():
    days = sessions(9, 10) + sessions(10, 5)
    shown = trends_of([group("g", ["2026-09-02", "2026-10-02", "2026-10-03"])], days, 0, {})
    assert [m["sessions"] for m in shown["months"]] == [10, 5]
    cells = shown["groups"][0]["cells"]
    assert [c["per10"] for c in cells] == [1.0, 4.0]
    assert [c["times"] for c in cells] == [1, 2]


def test_a_month_without_sessions_has_no_column():
    days = sessions(8, 4) + sessions(10, 4)
    shown = trends_of([group("g", ["2026-08-02"])], days, 0, {})
    assert [m["month"] for m in shown["months"]] == ["2026-08", "2026-10"]


def test_the_trend_word_comes_from_the_months():
    days = sessions(7, 10) + sessions(8, 10) + sessions(9, 10) + sessions(10, 10)
    gone = group("g", ["2026-07-02", "2026-07-03", "2026-08-02"])
    assert trends_of([gone], days, 0, {})["groups"][0]["trend"] == "gone"


def test_undated_sessions_and_cards_are_counted_not_placed():
    days = sessions(10, 10)
    shown = trends_of([group("g", ["2026-10-02", None, None]), group("u", [None])], days, 3, {})
    assert shown["undatedSessions"] == 3
    first, only_undated = shown["groups"]
    assert (first["undatedTimes"], first["cells"][0]["times"]) == (2, 1)
    assert only_undated["trend"] is None and only_undated["undatedTimes"] == 1


def test_one_offs_and_noise_are_left_out():
    groups = [group("a", ["2026-10-02"], recurring=False), group("b", ["2026-10-02"], noise="x")]
    assert trends_of(groups, sessions(10, 3), 0, {})["groups"] == []


def test_a_taught_group_shows_the_rate_before_and_after_the_taught_day():
    days = sessions(10, 20)
    seen = ["2026-10-02", "2026-10-03", "2026-10-04", "2026-10-15"]
    taught_day = {"g": Taught(date(2026, 10, 10), "Unset the token first.")}
    row = trends_of([group("g", seen)], days, 0, taught_day)["groups"][0]
    taught = row["taught"]
    assert taught["on"] == "2026-10-10" and taught["month"] == "2026-10"
    assert (taught["before"]["times"], taught["before"]["sessions"]) == (3, 10)
    assert (taught["after"]["times"], taught["after"]["sessions"]) == (1, 10)
    assert taught["after"]["per10"] == pytest.approx(1.0)
    assert taught["enough"] is True
    assert taught["lesson"] == "Unset the token first."


def test_a_group_not_taught_has_no_split():
    assert (
        trends_of([group("g", ["2026-10-02"])], sessions(10, 3), 0, {})["groups"][0]["taught"]
        is None
    )


def test_a_row_is_called_by_the_inbox_name_and_the_developers_rename_wins():
    shown = trends_of(
        [group("g", ["2026-10-02"]), group("h", ["2026-10-02"])],
        sessions(10, 3),
        0,
        {},
        {"h": "Flaky CI"},
    )
    assert [row["title"] for row in shown["groups"]] == ["g failing", "Flaky CI"]


def test_a_store_mined_before_incidents_says_its_dates_were_not_kept(tmp_path):
    store = Store.open(tmp_path / "s.db")
    mine_a_session_without_failures(tmp_path, store)
    assert trends_snapshot(store, "demo", None)["undatedReason"] == "old_store"
    assert trends_snapshot(store, "demo", {"groups": []})["undatedReason"] == "no_timestamps"


def test_occurrences_in_months_beyond_the_twelve_shown_are_counted_not_dropped():
    days = [date(2025 + (m - 1) // 12, (m - 1) % 12 + 1, 1) for m in range(1, 15)]
    seen = ["2025-01-01", "2025-02-01", "2026-02-01"]
    row = trends_of([group("g", seen)], days, 0, {})["groups"][0]
    assert row["outsideTimes"] == 2
    assert len(row["cells"]) == 12


def gone(key, dates):
    return group(key, dates)


def natural(groups, days):
    return trends_of(groups, days, 0, {})["natural"]


# Ten sessions in September, then October and November with nothing from the group.
QUIET_AFTER = sessions(9, 10) + sessions(10, 6) + sessions(11, 6)


def test_a_group_that_went_quiet_with_ten_sessions_since_is_the_found_before_and_after():
    found = natural([gone("g", ["2026-09-02", "2026-09-03"])], QUIET_AFTER)
    assert found["key"] == "g" and found["last"] == "2026-09-03"
    assert (found["before"]["times"], found["before"]["sessions"]) == (2, 3)
    assert (found["after"]["times"], found["after"]["sessions"]) == (0, 19)
    assert found["sessionsWithGroup"] == 2 and found["first"] == "2026-09-02"


def test_no_group_is_found_when_none_is_gone_with_ten_sessions_after_it():
    recent = sessions(9, 10) + sessions(10, 6) + sessions(11, 3)
    assert natural([gone("g", ["2026-10-03"])], recent) is None
    assert natural([gone("h", ["2026-11-02"])], QUIET_AFTER) is None


def test_the_found_group_has_the_most_occurrences_then_the_latest_last_day():
    many = gone("many", ["2026-09-02", "2026-09-02", "2026-09-03"])
    late = gone("late", ["2026-09-04", "2026-09-05"])
    early = gone("early", ["2026-09-01", "2026-09-02"])
    assert natural([early, late, many], QUIET_AFTER)["key"] == "many"
    assert natural([early, late], QUIET_AFTER)["key"] == "late"


def test_a_group_the_developer_taught_is_not_offered_as_one_they_did_not():
    taught = {"g": Taught(date(2026, 9, 4), "Unset it.")}
    shown = trends_of([gone("g", ["2026-09-02", "2026-09-03"])], QUIET_AFTER, 0, taught)
    assert shown["natural"] is None


def taught_group_store(tmp_path):
    store = Store.open(tmp_path / "s.db")
    mine_a_session_without_failures(tmp_path, store)
    store.curation.add_authored(
        "demo", AuthoredLesson("l1", "Unset the token first.", LessonKind.MISTAKE)
    )
    store.review.triage.mark_taught("demo", "g", date(2026, 10, 10), "l1")
    return store


def lesson_shown(store):
    return taught_lessons(store, "demo")["g"].lesson


def test_the_lesson_words_come_from_the_lessons_store(tmp_path):
    assert lesson_shown(taught_group_store(tmp_path)) == "Unset the token first."


def test_a_forgotten_lesson_leaves_no_words_to_show(tmp_path):
    store = taught_group_store(tmp_path)
    store.curation.forget_authored("demo", "l1")

    assert lesson_shown(store) is None


def test_a_group_taught_before_ids_were_kept_has_no_words_to_show(tmp_path):
    store = Store.open(tmp_path / "s.db")
    mine_a_session_without_failures(tmp_path, store)
    store.review.triage.mark_taught("demo", "g", date(2026, 10, 10))

    assert lesson_shown(store) is None
