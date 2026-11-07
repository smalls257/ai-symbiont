"""The `topicView` key of the dashboard data: what the developer worked on, by topic.

A topic bar that does not add up to its sessions, or a quiet month that vanishes from the
timeline, looks finished and misleads: outcomes are counted from the sessions listed and a quiet
month is a 0. Below the summary threshold `ready` is false and the page lists the sessions by date.
"""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from symbiont.miner.incident_types import Incident
from symbiont.miner.session_summary import SessionSummary, SummaryOutcome
from symbiont.miner.struggle import SessionFacts
from symbiont.miner.topics import Group, TopicMap
from symbiont.service.dataset_history import dataset_readers
from symbiont.service.session_dates import session_dates_of
from symbiont.service.week_axis import per_week, weeks_spanning
from symbiont.store.local import Store

# The same bar `topics/candidates` applies before it offers sessions for naming (summary_routes).
MIN_SUMMARIES = 30
OUTCOMES = [o.value for o in SummaryOutcome]
# How many goals a topic card quotes: enough to recognize the topic, few enough to stay short.
EXAMPLE_GOALS = 3


def topic_snapshot(store: Store, project: str) -> dict[str, Any]:
    """The `topicView` data of `project` from what the store keeps."""
    facts = store.mined.session_facts(project)
    summaries = store.review.summaries.all(project)
    view = topic_view(
        store.review.summaries.topics(project),
        summaries,
        store.mined.incidents(project),
        session_dates_of(facts),
        store.review.summaries.topic_names(project),
    )
    view["sessionsByDate"] = sessions_by_date(facts, summaries)
    view["datasetReaders"] = dataset_readers(store, project)
    return view


def sessions_by_date(
    facts: Sequence[SessionFacts], summaries: Sequence[SessionSummary]
) -> list[dict[str, Any]]:
    """Every mined session, newest first, undated last, from the facts so it is never empty.

    A session nobody summarized has a null outcome.
    """
    ended = {s.session_id: s.outcome.value for s in summaries if not s.noise}
    rows = [
        {"id": f.session_id, "date": f.started, "goal": f.title, "outcome": ended.get(f.session_id)}
        for f in facts
    ]
    return sorted(rows, key=lambda row: row["date"] or "", reverse=True)


def topic_view(
    topics: TopicMap,
    summaries: Sequence[SessionSummary],
    incidents: Sequence[Incident],
    dates: Mapping[str, date],
    names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Topics with outcomes, months, frictions and sessions (by date alone before topics exist).

    `names` are the developer's names by the model's topic name; a topic's `key` stays the
    model's name so a rename can address it.
    """
    real = {s.session_id: s for s in summaries if not s.noise}
    named = [g for g in topics.topics if _members(g, real)]
    ready = len(real) >= MIN_SUMMARIES and bool(named)
    months = _months(dates, real)
    weeks = weeks_spanning(_days_of(real, dates))
    return {
        "ready": ready,
        "needed": max(0, MIN_SUMMARIES - len(real)),
        "sessions": len(real),
        "noiseSessions": len(summaries) - len(real),
        "undated": sum(1 for sid in real if sid not in dates),
        "months": months,
        "allPerMonth": _per_month(real, dates, months),
        "weeks": weeks,
        "allPerWeek": per_week(_days_of(real, dates), weeks),
        "requests": None,
        "frictions": _frictions(topics.frictions, real),
        "topics": [
            _topic(g, Timeline(real, dates, months, weeks), topics, incidents, names or {})
            for g in named
        ]
        if ready
        else [],
    }


def _months(dates: Mapping[str, date], real: Collection[str]) -> list[str]:
    """Every month from the first to the last session day, quiet months included."""
    days = [dates[sid] for sid in real if sid in dates]
    if not days:
        return []
    first, last = min(days), max(days)
    count = (last.year - first.year) * 12 + last.month - first.month + 1
    return [_month_after(first, offset) for offset in range(count)]


def _month_after(first: date, offset: int) -> str:
    """`first`'s month moved forward by `offset` months, as YYYY-MM."""
    index = first.month - 1 + offset
    return f"{first.year + index // 12}-{index % 12 + 1:02d}"


def _per_month(ids: Collection[str], dates: Mapping[str, date], months: list[str]) -> list[int]:
    seen = Counter(dates[sid].isoformat()[:7] for sid in ids if sid in dates)
    return [seen.get(month, 0) for month in months]


def _sessions(
    real: Mapping[str, SessionSummary], dates: Mapping[str, date]
) -> list[dict[str, Any]]:
    """The sessions newest first; undated ones last, with a null date."""
    rows = [_session(s, dates) for s in real.values()]
    return sorted(rows, key=lambda row: row["date"] or "", reverse=True)


def _session(summary: SessionSummary, dates: Mapping[str, date]) -> dict[str, Any]:
    when = dates.get(summary.session_id)
    return {
        "id": summary.session_id,
        "date": when.isoformat() if when else None,
        "goal": summary.goal,
        "outcome": summary.outcome.value,
        "friction": summary.friction,
    }


def _frictions(groups: Sequence[Group], real: Mapping[str, SessionSummary]) -> list[dict[str, Any]]:
    return [
        {"name": g.name, "description": g.description, "sessions": len(_members(g, real))}
        for g in groups
    ]


def _members(group: Group, real: Mapping[str, SessionSummary]) -> set[str]:
    """The group's sessions, each once, that have a non-noise summary."""
    return {sid for sid in group.session_ids if sid in real}


@dataclass(frozen=True)
class Timeline:
    """The non-noise summaries, the session days and the month axis every topic shares."""

    real: Mapping[str, SessionSummary]
    dates: Mapping[str, date]
    months: list[str]
    weeks: list[str]


def _topic(
    group: Group,
    line: Timeline,
    topics: TopicMap,
    incidents: Sequence[Incident],
    names: Mapping[str, str],
) -> dict[str, Any]:
    real, dates, months = line.real, line.dates, line.months
    members = _members(group, real)
    outcomes = Counter(real[sid].outcome.value for sid in members)
    days = sorted(day.isoformat() for day in _days_of(members, dates))
    return {
        "key": group.name,
        "name": names.get(group.name, group.name),
        "description": group.description,
        "sessions": len(members),
        "outcomes": {name: outcomes.get(name, 0) for name in OUTCOMES},
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "perMonth": _per_month(members, dates, months),
        "perWeek": per_week(_days_of(members, dates), line.weeks),
        "examples": _examples(_sessions({sid: real[sid] for sid in members}, dates)),
        "frictions": {f.name: len(_members(f, real) & members) for f in topics.frictions},
        "incidents": _worth_looking_at(incidents, members),
        "sessionList": _sessions({sid: real[sid] for sid in members}, dates),
    }


def _days_of(ids: Collection[str], dates: Mapping[str, date]) -> list[date]:
    return [dates[sid] for sid in ids if sid in dates]


def _examples(sessions: Sequence[Mapping[str, Any]]) -> list[str]:
    """The first three distinct, non-empty goals of `sessions` (already newest first)."""
    goals = dict.fromkeys(row["goal"] for row in sessions if row["goal"])
    return list(goals)[:EXAMPLE_GOALS]


def _worth_looking_at(incidents: Sequence[Incident], members: Collection[str]) -> int:
    return sum(1 for c in incidents if c.session_id in members and c.noise is None)
