"""The week axis: quiet weeks are zeros and the year boundary uses ISO weeks."""

from datetime import date

from symbiont.service.week_axis import per_week, sessions_per_week, week_key, weeks_spanning


def test_quiet_weeks_between_two_days_are_on_the_axis():
    axis = weeks_spanning([date(2026, 10, 5), date(2026, 10, 21)])
    assert axis == ["2026-W41", "2026-W42", "2026-W43"]


def test_the_iso_year_wraps_at_the_new_year():
    assert week_key(date(2026, 12, 31)) == "2026-W53"
    assert weeks_spanning([date(2026, 12, 28), date(2027, 1, 4)]) == ["2026-W53", "2027-W01"]


def test_counts_per_week_include_zeros_and_no_days_means_no_axis():
    days = [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 21)]
    assert sessions_per_week(days) == [["2026-W41", 2], ["2026-W42", 0], ["2026-W43", 1]]
    assert per_week(days, weeks_spanning(days)) == [2, 0, 1]
    assert sessions_per_week([]) == []
