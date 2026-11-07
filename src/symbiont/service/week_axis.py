"""ISO weeks on one axis, so a group's weekly counts and the sessions per week line up.

A week with no sessions is a 0 on the axis, never missing: a gap in a chart must read as "none".
"""

from collections import Counter
from collections.abc import Iterable
from datetime import date, timedelta


def week_key(day: date) -> str:
    """The ISO week of `day` as YYYY-Www."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def weeks_spanning(days: Iterable[date]) -> list[str]:
    """Every ISO week from the earliest day's to the latest day's, quiet weeks included."""
    known = list(days)
    if not known:
        return []
    monday = min(known) - timedelta(days=min(known).weekday())
    last = week_key(max(known))
    keys = [week_key(monday)]
    while keys[-1] != last:
        monday += timedelta(weeks=1)
        keys.append(week_key(monday))
    return keys


def per_week(days: Iterable[date], axis: list[str]) -> list[int]:
    """How many of `days` fall in each week of `axis`."""
    seen = Counter(week_key(day) for day in days)
    return [seen.get(week, 0) for week in axis]


def sessions_per_week(days: Iterable[date]) -> list[list[object]]:
    """[ISO week, sessions] rows over the whole span of `days`, one day per session."""
    known = list(days)
    axis = weeks_spanning(known)
    return [[week, n] for week, n in zip(axis, per_week(known, axis), strict=True)]
