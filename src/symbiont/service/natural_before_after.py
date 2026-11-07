"""The before and after the developer already has: a failure that went quiet without a lesson.

A group that is "gone" and had at least `MIN_AFTER_SESSIONS` sessions since its last occurrence
shows what the comparison looks like once something is taught. Picked by rule, never by hand.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from symbiont.core.trends import Trend, Window, before_after


@dataclass(frozen=True)
class _Found:
    times: int
    last: date
    key: str
    row: Mapping[str, Any]
    group: Mapping[str, Any]
    days: tuple[date, ...]


def natural_before_after(
    groups: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    session_days: Sequence[date],
) -> dict[str, Any] | None:
    """The gone, untaught group with most occurrences (then the latest), or None when none fits.

    `rows` are the trend rows built from `groups`; the split is at the group's last day.
    """
    by_key = {group["key"]: group for group in groups}
    found = [
        _Found(len(seen), max(seen), row["key"], row, by_key[row["key"]], tuple(seen))
        for row in rows
        if row["trend"] == Trend.GONE.value and row["taught"] is None
        if (seen := _days_of(by_key[row["key"]]))
        if before_after(seen, session_days, max(seen)).after_is_enough
    ]
    if not found:
        return None
    best = min(found, key=lambda pick: (-pick.times, -pick.last.toordinal(), pick.key))
    return _described(best, session_days)


def _days_of(group: Mapping[str, Any]) -> list[date]:
    return [date.fromisoformat(card["date"]) for card in group["cards"] if card["date"]]


def _window(window: Window) -> dict[str, Any]:
    return {"times": window.times, "sessions": window.sessions, "per10": window.per_10}


def _described(found: _Found, session_days: Sequence[date]) -> dict[str, Any]:
    split = before_after(list(found.days), session_days, found.last)
    sessions = {card["sessionId"] for card in found.group["cards"] if card["date"]}
    return {
        "key": found.key,
        "title": found.row["title"],
        "kind": found.row["kind"],
        "first": min(found.days).isoformat(),
        "last": found.last.isoformat(),
        "sessionsWithGroup": len(sessions),
        "before": _window(split.before),
        "after": _window(split.after),
    }
