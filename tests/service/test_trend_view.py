"""The `trends` data: rates per 10 sessions by month, a trend word, before/after, undated left out.

Failure guarded against: undated sessions or cards read as a month's zero, a taught group with
no before/after, and a one-off or noise group cluttering the view.
"""

from datetime import date

import pytest

from symbiont.service.trend_view import trends_of


def group(key, dates, *, recurring=True, noise=None):
    last = max((d for d in dates if d), default=None)
    return {
        "key": key, "title": key, "kind": "failure", "last": last,
        "recurring": recurring, "noise": noise, "cards": [{"date": d} for d in dates],
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
    row = trends_of([group("g", seen)], days, 0, {"g": date(2026, 10, 10)})["groups"][0]
    taught = row["taught"]
    assert taught["on"] == "2026-10-10" and taught["month"] == "2026-10"
    assert (taught["before"]["times"], taught["before"]["sessions"]) == (3, 10)
    assert (taught["after"]["times"], taught["after"]["sessions"]) == (1, 10)
    assert taught["after"]["per10"] == pytest.approx(1.0)
    assert taught["enough"] is True


def test_a_group_not_taught_has_no_split():
    assert (
        trends_of([group("g", ["2026-10-02"])], sessions(10, 3), 0, {})["groups"][0]["taught"]
        is None
    )
