"""The `incidents` key of the dashboard data: the review Inbox's groups, and the cards by topic.

Cards are dated by their session (null when the session has no timestamps) and grouped by
fingerprint (see `miner.incident_groups`). Noise is counted with its reason, never hidden.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from symbiont.miner.incident_groups import (
    IncidentGroup,
    SessionDays,
    group_incidents,
    newest_first,
)
from symbiont.miner.incident_types import Incident, Outcome, Trigger
from symbiont.miner.incidents import noise_words
from symbiont.miner.painpoint import Signal
from symbiont.service.session_dates import session_dates_of
from symbiont.store.local import Store

VERDICT_WORDS = {
    Outcome.FIXED_IN_CODE: "fixed in the code",
    Outcome.ENVIRONMENT_FIXED: "fixed by setting something up",
    Outcome.CORRECTED_COMMAND: "went through when run correctly",
    Outcome.PASSED_ON_RETRY: "passed when run again",
    Outcome.NEVER_FIXED: "never fixed",
    Outcome.DEVELOPER_STEPPED_IN: "you stepped in",
}
FIXED_OUTCOMES = frozenset({Outcome.FIXED_IN_CODE, Outcome.ENVIRONMENT_FIXED})
MIN_RECURRING_SESSIONS = 2
NAME_CHARS = 80  # the most a group name may hold (POST /triage refuses longer)
SINGLE_CORRECTION = "One correction, on its own."


@dataclass(frozen=True)
class IncidentContext:
    """What the cards are told against: session titles and the session model's descriptions."""

    titles: Mapping[str, str] = field(default_factory=dict)
    topic_descriptions: Mapping[str, str] = field(default_factory=dict)
    correction_names: Mapping[tuple[str, int], str] = field(default_factory=dict)
    correction_descriptions: Mapping[str, str] = field(default_factory=dict)


def incidents_snapshot(store: Store, project: str) -> dict[str, Any]:
    """The `incidents` data of `project`, with today's topic names and session titles."""
    facts = store.mined.session_facts(project)
    topic_map = store.review.summaries.topics(project)
    topic_of = {sid: g.name for g in topic_map.topics for sid in g.session_ids}
    cards = [
        replace(card, topic=topic_of.get(card.session_id, ""))
        for card in store.mined.incidents(project)
    ]
    groups = topic_map.correction_groups
    context = IncidentContext(
        {f.session_id: f.title for f in facts},
        {g.name: g.description for g in topic_map.topics},
        {ref: g.name for g in groups for ref in g.refs},
        {g.name: g.description for g in groups},
    )
    days = {sid: when.isoformat() for sid, when in session_dates_of(facts).items()}
    return incident_groups(cards, days, context)


def incident_groups(
    incidents: Sequence[Incident], days: SessionDays, context: IncidentContext | None = None
) -> dict[str, Any]:
    """Groups for the Inbox, cards by topic, and the noise with its reasons."""
    context = context or IncidentContext()
    return {
        "groups": [
            _group_json(g, days, context)
            for g in group_incidents(incidents, days, context.correction_names)
        ],
        "topics": _topics(incidents, days, context),
        "noise": _noise_totals(incidents),
        "noTopic": [_card(c, days, context) for c in newest_first(_worth(incidents, ""), days)],
    }


def _worth(incidents: Sequence[Incident], topic: str) -> list[Incident]:
    return [c for c in incidents if c.topic == topic and c.noise is None]


def _card(card: Incident, days: SessionDays, context: IncidentContext) -> dict[str, Any]:
    return {
        "happened": card.what_happened,
        "fixed": card.what_fixed_it,
        "outcome": card.outcome.value,
        "noise": card.noise.value if card.noise else None,
        "noiseWords": noise_words(card.noise) if card.noise else "",
        "date": days.get(card.session_id),
        "files": list(card.files),
        "firstWrong": card.first_wrong,
        "costSteps": card.cost_steps,
        "session": context.titles.get(card.session_id, ""),
    }


def _topics(
    incidents: Sequence[Incident], days: SessionDays, context: IncidentContext
) -> list[dict[str, Any]]:
    names = sorted({c.topic for c in incidents if c.topic})
    entries = [_topic_entry(name, incidents, days, context) for name in names]
    return sorted(entries, key=lambda entry: (-len(entry["worth"]), entry["topic"]))


def _topic_entry(
    name: str, incidents: Sequence[Incident], days: SessionDays, context: IncidentContext
) -> dict[str, Any]:
    mine = [c for c in incidents if c.topic == name]
    noise = Counter(c.noise.value for c in mine if c.noise)
    return {
        "topic": name,
        "description": context.topic_descriptions.get(name, ""),
        "sessions": len({c.session_id for c in mine}),
        "worth": [_card(c, days, context) for c in newest_first(_worth(incidents, name), days)],
        "noise": dict(noise),
    }


def _noise_totals(incidents: Sequence[Incident]) -> dict[str, Any]:
    counted = Counter(c.noise for c in incidents if c.noise)
    by_reason = [{"reason": noise_words(r), "count": n} for r, n in counted.most_common()]
    return {"total": sum(counted.values()), "byReason": by_reason}


def _group_json(
    group: IncidentGroup, days: SessionDays, context: IncidentContext
) -> dict[str, Any]:
    newest = group.cards[0]
    weeks, undated = _weekly(group.cards, days)
    return {
        "key": group.key,
        "name": _generated_name(group),
        "title": newest.example or newest.what_happened,
        "groupedBecause": _grouped_because(group, context),
        "kind": "correction" if group.signal is Signal.CORRECTION else "failure",
        "happened": newest.what_happened,
        "fixed": newest.what_fixed_it,
        "verdict": _verdict(group.cards),
        "noise": group.noise.value if group.noise else None,
        "noiseWords": noise_words(group.noise) if group.noise else "",
        "sessions": len({c.session_id for c in group.cards}),
        "times": len(group.cards),
        "recurring": _recurring(group.cards),
        "weekly": weeks,
        "undated": undated,
        **_first_and_last(group.cards, days),
        "cards": [_card(c, days, context) for c in group.cards],
        "trigger": _trigger_json(group.trigger),
    }


def _generated_name(group: IncidentGroup) -> str:
    """The heading a group has until the developer renames it, at most NAME_CHARS long.

    A correction group is called what the session model named it; a failure group by its program
    and what broke, so two groups of the same program do not read alike.
    """
    named = group.key.removeprefix("correction:")
    if group.signal is Signal.CORRECTION:
        known = named != group.key and ":" not in named
        return _shortened(named if known else group.cards[0].what_happened)
    _, program, broke = (group.key.split(":", 2) + ["", ""])[:3]
    if program and broke:
        return _shortened(f"{program} failing with {broke}")
    return _shortened(group.cards[0].what_happened)


def _shortened(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= NAME_CHARS else one_line[: NAME_CHARS - 1] + "\u2026"


def _recurring(cards: Sequence[Incident]) -> bool:
    """Seen in two or more sessions, or a fix was shown: the owner asked not to see one-offs."""
    fixed = any(c.outcome in FIXED_OUTCOMES for c in cards)
    return fixed or len({c.session_id for c in cards}) >= MIN_RECURRING_SESSIONS


def _verdict(cards: Sequence[Incident]) -> str:
    return VERDICT_WORDS[Counter(c.outcome for c in cards).most_common(1)[0][0]]


def _first_and_last(cards: Sequence[Incident], days: SessionDays) -> dict[str, str | None]:
    known = sorted(day for day in (days.get(c.session_id) for c in cards) if day)
    return {"first": known[0] if known else None, "last": known[-1] if known else None}


def _trigger_json(trigger: Trigger | None) -> dict[str, str] | None:
    if trigger is None:
        return None
    return {
        "kind": trigger.kind.value,
        "program": trigger.program,
        "path": trigger.path,
        "words": trigger.words,
    }


def _grouped_because(group: IncidentGroup, context: IncidentContext) -> str:
    newest = group.cards[0]
    if group.signal is not Signal.CORRECTION:
        program = newest.situation[1]
        return f"Every card is {program} failing the same way."
    name = group.key.removeprefix("correction:")
    return context.correction_descriptions.get(name) or (
        SINGLE_CORRECTION if len(group.cards) == 1 else "Corrections the developer repeats."
    )


def _weekly(cards: Sequence[Incident], days: SessionDays) -> tuple[list[list[Any]], int]:
    weeks: Counter[str] = Counter()
    for card in cards:
        day = days.get(card.session_id)
        if day:
            year, week, _ = date.fromisoformat(day).isocalendar()
            weeks[f"{year}-W{week:02d}"] += 1
    return [[week, n] for week, n in sorted(weeks.items())], sum(
        1 for c in cards if not days.get(c.session_id)
    )
