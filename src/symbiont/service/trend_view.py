"""The `trends` key of the dashboard data: "Is it getting better?" (rates in `core.trends`).

Undated sessions and cards are left out of every rate and counted, never read as a zero month.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from symbiont.core.trends import Window, before_after, rate_per_10, trend_of
from symbiont.service.natural_before_after import natural_before_after
from symbiont.service.session_dates import session_dates_of
from symbiont.store.local import Store


@dataclass(frozen=True)
class Taught:
    """The day a group was taught to the agent and the words ("" when none were kept)."""

    on: date
    lesson: str = ""


# A year of columns is as many as the table can show without squeezing the numbers.
SHOWN_MONTHS = 12


@dataclass(frozen=True)
class Calendar:
    """Sessions per month with sessions (oldest first) and the months the table shows."""

    per_month: Mapping[str, int]
    months: Sequence[str]
    shown: Sequence[str]


def trends_snapshot(
    store: Store, project: str, incidents: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The `trends` data of `project`, from the page's `incidents` data; read-only.

    No incidents (an old store) means its dates were never kept: `undatedReason` says so.
    """
    facts = store.mined.session_facts(project)
    session_days = list(session_dates_of(facts).values())
    triage = store.review.triage
    words = triage.lessons(project)
    taught = {
        key: Taught(row.taught_on, words.get(key, ""))
        for key, row in triage.all(project).items()
        if row.taught_on
    }
    groups = incidents["groups"] if incidents else []
    shown = trends_of(
        groups, session_days, len(facts) - len(session_days), taught, triage.names(project)
    )
    return {**shown, "undatedReason": "no_timestamps" if incidents else "old_store"}


def trends_of(
    groups: Sequence[Mapping[str, Any]],
    session_days: Sequence[date],
    undated_sessions: int,
    taught: Mapping[str, Taught],
    names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Trends for the recurring, non-noise groups, each named as the Inbox names it."""
    per_month = Counter(_month(day) for day in session_days)
    months = sorted(per_month)
    shown = months[-SHOWN_MONTHS:]
    calendar = Calendar(per_month, months, shown)
    rows = [
        _group_row(g, calendar, session_days, taught.get(g["key"]), (names or {}).get(g["key"]))
        for g in groups
        if g["recurring"] and g["noise"] is None
    ]
    return {
        "months": [{"month": m, "sessions": per_month[m]} for m in shown],
        "undatedSessions": undated_sessions,
        "groups": rows,
        "natural": natural_before_after(groups, rows, session_days),
    }


def _month(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def _group_row(
    group: Mapping[str, Any],
    calendar: Calendar,
    session_days: Sequence[date],
    taught: Taught | None,
    chosen_name: str | None,
) -> dict[str, Any]:
    seen = [date.fromisoformat(c["date"]) for c in group["cards"] if c["date"]]
    times = Counter(_month(day) for day in seen)
    return {
        "key": group["key"],
        "title": chosen_name or group["name"],
        "kind": group["kind"],
        "last": group["last"],
        "trend": _trend(seen, times, calendar),
        "undatedTimes": len(group["cards"]) - len(seen),
        "outsideTimes": sum(n for month, n in times.items() if month not in calendar.shown),
        "cells": [_cell(times[m], calendar.per_month[m]) for m in calendar.shown],
        "taught": _taught(seen, session_days, taught),
    }


def _trend(seen: Sequence[date], times: Mapping[str, int], calendar: Calendar) -> str | None:
    if not seen:
        return None
    return trend_of([(times[m], calendar.per_month[m]) for m in calendar.months]).value


def _cell(times: int, sessions: int) -> dict[str, Any]:
    return {"times": times, "sessions": sessions, "per10": rate_per_10(times, sessions)}


def _taught(
    seen: Sequence[date], session_days: Sequence[date], taught: Taught | None
) -> dict[str, Any] | None:
    if taught is None:
        return None
    split = before_after(seen, session_days, taught.on)
    return {
        "on": taught.on.isoformat(),
        "month": _month(taught.on),
        "lesson": taught.lesson,
        "before": _window(split.before),
        "after": _window(split.after),
        "enough": split.after_is_enough,
    }


def _window(window: Window) -> dict[str, Any]:
    return _cell(window.times, window.sessions)
