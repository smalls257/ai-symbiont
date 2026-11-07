"""Is a failure fading, and did a lesson help? Rates per 10 sessions, never raw counts.

Failure guarded against: a month with few sessions or none reading as a swing (or as a zero
rate) in the trend, and a lesson judged on counts that ignore how many sessions ran.
"""

from datetime import date, timedelta

import pytest

from symbiont.core.trends import (
    MIN_TREND_OCCURRENCES,
    QUIET_MONTHS,
    Trend,
    badge_of,
    before_after,
    rate_per_10,
    trend_of,
)


def test_rate_is_per_ten_sessions_and_unknown_without_sessions():
    assert rate_per_10(3, 12) == pytest.approx(2.5)
    assert rate_per_10(0, 0) is None


def test_more_in_the_last_two_months_than_before_is_rising():
    months = [(1, 10), (1, 10), (1, 10), (4, 10), (5, 10)]
    assert trend_of(months) is Trend.RISING


def test_about_the_same_rate_is_steady():
    assert trend_of([(2, 10), (3, 10), (2, 10), (3, 10)]) is Trend.STEADY


def test_far_less_in_the_last_two_months_is_fading():
    assert trend_of([(6, 10), (5, 10), (1, 10), (1, 10)]) is Trend.FADING


def test_none_in_the_last_quiet_months_is_gone():
    assert QUIET_MONTHS == 2
    assert trend_of([(6, 10), (5, 10), (0, 10), (0, 8)]) is Trend.GONE


def test_one_quiet_month_is_not_gone():
    assert trend_of([(6, 10), (5, 10), (3, 10), (0, 8)]) is not Trend.GONE


def test_a_month_without_sessions_is_skipped_not_a_zero_rate():
    # Counting the empty months as zero would make the last two months quiet (gone).
    assert trend_of([(6, 10), (5, 10), (0, 0), (0, 0)]) is Trend.STEADY
    assert trend_of([(3, 10), (3, 10), (0, 0), (3, 10), (3, 10)]) is Trend.STEADY


def test_a_busy_month_outweighs_a_thin_one():
    # 1 in 1 session is a huge rate, but only one session; pooled it barely moves.
    assert trend_of([(5, 10), (5, 10), (5, 10), (1, 1)]) is Trend.STEADY


def test_nothing_to_compare_with_is_steady():
    assert trend_of([(2, 10), (3, 10)]) is Trend.STEADY


def test_a_group_never_seen_in_any_month_is_refused():
    with pytest.raises(ValueError, match="never"):
        trend_of([(0, 10), (0, 10), (0, 5)])


def d(month, day):
    return date(2026, month, day)


def test_before_and_after_compare_rates_around_the_taught_day():
    sessions = [d(10, 1), d(10, 2), d(10, 3), d(10, 4), d(10, 6), d(10, 8), d(10, 9), d(10, 10)]
    seen = [d(10, 1), d(10, 1), d(10, 3), d(10, 9)]
    split = before_after(seen, sessions, taught_on=d(10, 4))
    assert (split.before.times, split.before.sessions) == (3, 4)
    assert (split.after.times, split.after.sessions) == (1, 4)
    assert split.before.per_10 == pytest.approx(7.5)
    assert split.after.per_10 == pytest.approx(2.5)


def test_the_taught_day_itself_counts_before_the_lesson():
    split = before_after([d(10, 4)], [d(10, 4), d(10, 5)], taught_on=d(10, 4))
    assert (split.before.times, split.after.times) == (1, 0)


def test_the_after_rate_is_unproven_until_ten_sessions_have_run():
    few = before_after([], [d(10, day) for day in range(1, 10)], taught_on=d(10, 2))
    assert not few.after_is_enough
    many = before_after([], [d(10, day) for day in range(1, 20)], taught_on=d(10, 2))
    assert many.after_is_enough


def test_no_sessions_after_the_lesson_has_no_after_rate():
    split = before_after([d(10, 1)], [d(10, 1)], taught_on=d(10, 5))
    assert split.after.per_10 is None


def test_too_few_occurrences_are_not_called_rising_or_fading():
    assert MIN_TREND_OCCURRENCES == 3
    assert trend_of([(0, 10), (0, 10), (1, 10), (1, 10)]) is Trend.TOO_FEW
    assert trend_of([(0, 10), (0, 10), (1, 10), (2, 10)]) is Trend.RISING


LATEST = date(2026, 8, 31)  # ISO week 2026-W36


def weeks_before_latest(counts):
    """Per-week counts, oldest first, ending at LATEST's week, as [week, n] rows."""
    rows = []
    for back, n in zip(range(len(counts) - 1, -1, -1), counts, strict=True):
        year, week, _ = (LATEST - timedelta(weeks=back)).isocalendar()
        rows.append([f"{year}-W{week:02d}", n])
    return rows


def badge(group, sessions, first=date(2026, 2, 1)):
    return badge_of(weeks_before_latest(group), weeks_before_latest(sessions), first, LATEST)


def test_a_group_first_seen_within_31_days_of_the_newest_session_is_new():
    assert badge([0] * 15 + [1], [5] * 16, first=date(2026, 8, 1)) == "new"
    assert badge([0] * 15 + [1], [5] * 16, first=date(2026, 7, 31)) == "new"
    assert badge([0] * 15 + [1], [5] * 16, first=date(2026, 7, 29)) is None


def test_more_per_session_in_the_last_8_weeks_than_the_8_before_is_rising():
    assert badge([0] * 6 + [1, 1] + [0] * 6 + [1, 8], [4] * 16) == "rising"


def test_a_rise_below_three_occurrences_or_without_the_factor_is_not_rising():
    assert badge([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1], [4] * 16) is None
    assert badge([2, 2, 2, 2, 0, 0, 0, 0, 2, 2, 2, 2, 2, 0, 0, 0], [4] * 16) is None


def test_the_same_count_over_fewer_sessions_is_rising_per_session():
    earlier, recent = [3] + [0] * 7, [3] + [0] * 7
    assert badge(earlier + recent, [10] * 8 + [2] * 8) == "rising"


def test_a_group_quiet_for_16_weeks_has_no_badge():
    assert badge([0] * 16, [4] * 16) is None
    assert badge_of([], [], None, LATEST) is None
