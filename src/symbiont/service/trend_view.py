"""The `trends` key of the dashboard data: "Is it getting better?" (rates in `core.trends`).

Undated sessions and cards are left out of every rate and counted, never read as a zero month.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from symbiont.core.trends import Window, before_after, rate_per_10, trend_of
from symbiont.service.session_dates import session_dates_of
from symbiont.store.local import Store

# A year of columns is as many as the table can show without squeezing the numbers.
SHOWN_MONTHS = 12


@dataclass(frozen=True)
class Calendar:
    """Sessions per month with sessions (oldest first) and the months the table shows."""

    per_month: Mapping[str, int]
    months: Sequence[str]
    shown: Sequence[str]


def trends_snapshot(store: Store, project: str, incidents: Mapping[str, Any]) -> dict[str, Any]:
    """The `trends` data of `project`, from the `incidents` data already built for the page.

    Read-only: a regression is derived by `triage_listing`, `changed_on` is never re-stamped here.
    """
    facts = store.mined.session_facts(project)
    session_days = list(session_dates_of(facts).values())
    taught = {
        key: row.taught_on for key, row in store.review.triage.all(project).items() if row.taught_on
    }
    return trends_of(incidents["groups"], session_days, len(facts) - len(session_days), taught)


def trends_of(
    groups: Sequence[Mapping[str, Any]],
    session_days: Sequence[date],
    undated_sessions: int,
    taught: Mapping[str, date],
) -> dict[str, Any]:
    """Trends for the recurring, non-noise groups; `groups` are the incident groups' JSON."""
    per_month = Counter(_month(day) for day in session_days)
    months = sorted(per_month)
    shown = months[-SHOWN_MONTHS:]
    calendar = Calendar(per_month, months, shown)
    rows = [
        _group_row(g, calendar, session_days, taught.get(g["key"]))
        for g in groups
        if g["recurring"] and g["noise"] is None
    ]
    return {
        "months": [{"month": m, "sessions": per_month[m]} for m in shown],
        "undatedSessions": undated_sessions,
        "groups": rows,
    }


def _month(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def _group_row(
    group: Mapping[str, Any],
    calendar: Calendar,
    session_days: Sequence[date],
    taught_on: date | None,
) -> dict[str, Any]:
    seen = [date.fromisoformat(c["date"]) for c in group["cards"] if c["date"]]
    times = Counter(_month(day) for day in seen)
    return {
        "key": group["key"],
        "title": group["title"],
        "kind": group["kind"],
        "last": group["last"],
        "trend": _trend(seen, times, calendar),
        "undatedTimes": len(group["cards"]) - len(seen),
        "cells": [_cell(times[m], calendar.per_month[m]) for m in calendar.shown],
        "taught": _taught(seen, session_days, taught_on),
    }


def _trend(seen: Sequence[date], times: Mapping[str, int], calendar: Calendar) -> str | None:
    if not seen:
        return None
    return trend_of([(times[m], calendar.per_month[m]) for m in calendar.months]).value


def _cell(times: int, sessions: int) -> dict[str, Any]:
    return {"times": times, "sessions": sessions, "per10": rate_per_10(times, sessions)}


def _taught(
    seen: Sequence[date], session_days: Sequence[date], taught_on: date | None
) -> dict[str, Any] | None:
    if taught_on is None:
        return None
    split = before_after(seen, session_days, taught_on)
    return {
        "on": taught_on.isoformat(),
        "month": _month(taught_on),
        "before": _window(split.before),
        "after": _window(split.after),
        "enough": split.after_is_enough,
    }


def _window(window: Window) -> dict[str, Any]:
    return _cell(window.times, window.sessions)
