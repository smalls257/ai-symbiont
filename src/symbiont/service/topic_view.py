"""The `topicView` key of the dashboard data: what the developer worked on, by topic.

A topic bar that does not add up to its sessions, or a month
with no sessions that vanishes from the timeline, looks finished and misleads. Outcomes are
counted from the sessions listed, a quiet month is a 0, and a session counts once per friction.
Below the summary threshold `ready` is false, so the page shows the instruction and the plain
sessions-by-date list instead of empty topic sections. Pure over what the store hands in.
"""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from symbiont.miner.incident_types import Incident
from symbiont.miner.session_summary import SessionSummary, SummaryOutcome
from symbiont.miner.topics import Group, TopicMap
from symbiont.service.session_dates import session_dates_of
from symbiont.store.local import Store

# The same bar `topics/candidates` applies before it offers sessions for naming (summary_routes).
MIN_SUMMARIES = 30
OUTCOMES = [o.value for o in SummaryOutcome]


def topic_snapshot(store: Store, project: str) -> dict[str, Any]:
    """The `topicView` data of `project` from what the store keeps."""
    return topic_view(
        store.review.summaries.topics(project),
        store.review.summaries.all(project),
        store.mined.incidents(project),
        session_dates_of(store.mined.session_facts(project)),
    )


def topic_view(
    topics: TopicMap,
    summaries: Sequence[SessionSummary],
    incidents: Sequence[Incident],
    dates: Mapping[str, date],
) -> dict[str, Any]:
    """Topics with outcomes, months, frictions and sessions (by date alone before topics exist)."""
    real = {s.session_id: s for s in summaries if not s.noise}
    ready = len(real) >= MIN_SUMMARIES and bool(topics.topics)
    months = _months(dates, real)
    return {
        "ready": ready,
        "needed": max(0, MIN_SUMMARIES - len(real)),
        "sessions": len(real),
        "noiseSessions": len(summaries) - len(real),
        "undated": sum(1 for sid in real if sid not in dates),
        "months": months,
        "allPerMonth": _per_month(real, dates, months),
        "frictions": _frictions(topics.frictions, real),
        "topics": [
            _topic(g, Timeline(real, dates, months), topics, incidents) for g in topics.topics
        ]
        if ready
        else [],
        "sessionsByDate": _sessions(real, dates),
    }


def _months(dates: Mapping[str, date], real: Collection[str]) -> list[str]:
    """Every month from the first to the last session day, quiet months included."""
    days = [dates[sid] for sid in real if sid in dates]
    if not days:
        return []
    first, last = min(days), max(days)
    count = (last.year - first.year) * 12 + last.month - first.month + 1
    return [f"{first.year + (first.month - 1 + i) // 12}-{(first.month - 1 + i) % 12 + 1:02d}"
            for i in range(count)]  # fmt: skip


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


def _topic(
    group: Group, line: Timeline, topics: TopicMap, incidents: Sequence[Incident]
) -> dict[str, Any]:
    real, dates, months = line.real, line.dates, line.months
    members = _members(group, real)
    outcomes = Counter(real[sid].outcome.value for sid in members)
    days = sorted(dates[sid].isoformat() for sid in members if sid in dates)
    return {
        "name": group.name,
        "description": group.description,
        "sessions": len(members),
        "outcomes": {name: outcomes.get(name, 0) for name in OUTCOMES},
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "perMonth": _per_month(members, dates, months),
        "frictions": {f.name: len(_members(f, real) & members) for f in topics.frictions},
        "incidents": sum(1 for c in incidents if c.session_id in members and c.noise is None),
        "sessionList": _sessions({sid: real[sid] for sid in members}, dates),
    }
