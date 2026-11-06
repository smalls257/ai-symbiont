"""Where sessions sit in time: every date comes from the session itself, or is unknown.

Sessions whose history carries no timestamps (OpenHands) were once dated `today` or by their log
file's mtime, so every card claimed the day the page was opened. A missing date stays `None` all
the way to the page, which says "date unknown"; the replay leaves such sessions out and counts them.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

REPLAY_DAYS = 30

SessionOrder = Mapping[str, tuple[int, date | None]]


def order_sessions(
    ids: Sequence[str], dates: Mapping[str, date]
) -> dict[str, tuple[int, date | None]]:
    """Session id -> (index, date or None): dated sessions oldest first, then the undated ones."""
    unique = list(dict.fromkeys(ids))
    dated = sorted((sid for sid in unique if sid in dates), key=lambda sid: dates[sid])
    ranked = dated + [sid for sid in unique if sid not in dates]
    return {sid: (index, dates.get(sid)) for index, sid in enumerate(ranked)}


def undated_count(order: SessionOrder) -> int:
    """How many sessions have no known date."""
    return sum(1 for _, when in order.values() if when is None)


def first_date(order: SessionOrder, today: date) -> date:
    """The oldest known session day; `today` only anchors the day numbers when none is known."""
    return min((when for _, when in order.values() if when is not None), default=today)


def day_offsets(order: SessionOrder, first: date) -> dict[int, int | None]:
    """Session index -> days since `first`, None for a session with no date."""
    return {index: None if when is None else (when - first).days for index, when in order.values()}


def replay(
    points: list[dict[str, Any]], day_of: Mapping[int, int | None], last_day: int, undated: int
) -> dict[str, Any]:
    """Repeats in the last REPLAY_DAYS that a note would have come before (an estimate).

    Repeats in sessions without a date are left out; `undated` says how many sessions that is.
    """
    start = max(0, last_day - REPLAY_DAYS)
    items = [
        {
            "painPointId": point["id"],
            "sessionIndex": index,
            "day": day,
            "turnsSaved": point["turnsPerOccurrence"],
            "minutesSaved": point["minutesPerOccurrence"],
        }
        for point in points
        for index in point["sessions"][1:]
        if (day := day_of[index]) is not None and day >= start
    ]
    return {
        "windowStartDay": start,
        "items": sorted(items, key=lambda item: item["day"]),
        "undated": undated,
    }
