"""Is a failure getting better: a monthly rate per 10 sessions, a trend word, a before/after.

A raw count per month measures how much the developer worked, not whether the failure faded.
A month with no sessions says nothing, so it is skipped, not read as a zero rate. Pure: no clock.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

# Two months with sessions and no occurrence: one quiet month is common (a different kind of
# work), two in a row is the pattern having stopped. Mockup v3 (Task 11) used the same window.
QUIET_MONTHS = 2
# The last two months with sessions are "now"; everything before them is "earlier".
RECENT_MONTHS = 2
# The recent rate must be half again the earlier one, and at least this much per 10 sessions,
# before it is called rising: a jump from 0.1 to 0.2 is noise, not a trend.
RISING_FACTOR = 1.5
RISING_FLOOR_PER_10 = 0.5
# Below this fraction of the earlier rate it is fading.
FADING_FACTOR = 0.6
# Fewer occurrences than this in all months say nothing about direction: two sightings one month
# apart look like a rise or a fade whichever way they fall, so the word would be a guess.
MIN_TREND_OCCURRENCES = 3
# After a lesson, fewer than this many sessions cannot show whether it worked (mockup v3 text).
MIN_AFTER_SESSIONS = 10


class Trend(StrEnum):
    """Which way a failure group is heading."""

    RISING = "rising"
    STEADY = "steady"
    FADING = "fading"
    GONE = "gone"
    TOO_FEW = "too_few"


@dataclass(frozen=True)
class Window:
    """Occurrences of a group across some sessions."""

    times: int
    sessions: int

    @property
    def per_10(self) -> float | None:
        """Times per 10 sessions; None when no session ran (an unknown rate, not zero)."""
        return rate_per_10(self.times, self.sessions)


@dataclass(frozen=True)
class BeforeAfter:
    """A group's rate before and after the day the developer taught the agent about it."""

    before: Window
    after: Window

    @property
    def after_is_enough(self) -> bool:
        """Whether enough sessions ran after the lesson to read the after-rate."""
        return self.after.sessions >= MIN_AFTER_SESSIONS


def rate_per_10(times: int, sessions: int) -> float | None:
    """`times` per 10 sessions, or None when there were no sessions."""
    return None if sessions <= 0 else 10 * times / sessions


def trend_of(per_month: Sequence[tuple[int, int]]) -> Trend:
    """The trend of (occurrences, sessions) per month, oldest first; ValueError if never seen.

    Months with no sessions are skipped. Pooled rates, so a thin month cannot swing the word.
    """
    months = [month for month in per_month if month[1] > 0]
    if not any(times for times, _ in months):
        raise ValueError("the group was never seen in a month with sessions")
    if not any(times for times, _ in months[-QUIET_MONTHS:]):
        return Trend.GONE
    earlier = months[:-RECENT_MONTHS]
    if not earlier:
        return Trend.STEADY
    word = _compared(_pooled(months[-RECENT_MONTHS:]), _pooled(earlier))
    return _gated(word, sum(times for times, _ in months))


def _gated(word: Trend, seen: int) -> Trend:
    """Rising and fading need MIN_TREND_OCCURRENCES behind them; fewer is "too few to tell"."""
    if word in (Trend.RISING, Trend.FADING) and seen < MIN_TREND_OCCURRENCES:
        return Trend.TOO_FEW
    return word


def _pooled(months: Sequence[tuple[int, int]]) -> float:
    return 10 * sum(times for times, _ in months) / sum(sessions for _, sessions in months)


def _compared(recent: float, earlier: float) -> Trend:
    if recent > RISING_FACTOR * earlier and recent > RISING_FLOOR_PER_10:
        return Trend.RISING
    if recent < FADING_FACTOR * earlier:
        return Trend.FADING
    return Trend.STEADY


def before_after(
    seen: Sequence[date], session_days: Sequence[date], taught_on: date
) -> BeforeAfter:
    """Occurrences (`seen`: one day per occurrence) and sessions split at `taught_on`.

    The taught day counts as before: a lesson written mid-session cannot have helped it yet.
    """
    return BeforeAfter(
        Window(_up_to(seen, taught_on), _up_to(session_days, taught_on)),
        Window(
            len(seen) - _up_to(seen, taught_on), len(session_days) - _up_to(session_days, taught_on)
        ),
    )


def _up_to(days: Sequence[date], last: date) -> int:
    return sum(1 for day in days if day <= last)


# A group first seen within this many days of the newest session is "new": the mockup's rule.
NEW_WITHIN_DAYS = 31
# Rising compares this many weeks with the same number before them (mockup v3 `trendOf`).
BADGE_WEEKS = 8


def badge_of(
    weekly: Sequence[Sequence[Any]],
    sessions_per_week: Sequence[Sequence[Any]],
    first: date | None,
    latest_day: date | None,
) -> str | None:
    """The badge word (new or rising) or None; `latest_day` is the newest session day, no clock.

    Rows are [ISO week, count]. Rising: the last 8 weeks' rate per session beats 1.5 times the
    8 before, with at least MIN_TREND_OCCURRENCES in the last 8 (the mockup's `trendOf`).
    """
    if first is None or latest_day is None:
        return None
    if (latest_day - first).days <= NEW_WITHIN_DAYS:
        return "new"
    axis = _week_keys_ending(latest_day, 2 * BADGE_WEEKS)
    seen, ran = _halves(axis, weekly), _halves(axis, sessions_per_week)
    (before, now), (sessions_before, sessions_now) = seen, ran
    rate_now, rate_before = now / max(sessions_now, 1), before / max(sessions_before, 1)
    if now >= MIN_TREND_OCCURRENCES and rate_now > RISING_FACTOR * rate_before:
        return "rising"
    return None


def _week_keys_ending(day: date, count: int) -> list[str]:
    """ISO week keys (YYYY-Www) of the `count` weeks up to `day`'s, oldest first."""
    keys = []
    for back in range(count - 1, -1, -1):
        year, week, _ = (day - timedelta(weeks=back)).isocalendar()
        keys.append(f"{year}-W{week:02d}")
    return keys


def _halves(axis: Sequence[str], rows: Sequence[Sequence[Any]]) -> tuple[int, int]:
    """The rows' counts summed over the first and the second half of `axis`."""
    counts = {str(week): int(n) for week, n in rows}
    half = len(axis) // 2
    return sum(counts.get(k, 0) for k in axis[:half]), sum(counts.get(k, 0) for k in axis[half:])
