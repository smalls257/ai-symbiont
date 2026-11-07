"""The `incidents` key of the dashboard data: the review Inbox's groups, and the cards by topic.

Cards are dated by their session (null when the session has no timestamps) and grouped by
fingerprint (see `miner.incident_groups`). Noise is counted with its reason, never hidden.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from symbiont.core.trends import badge_of
from symbiont.miner.group_names import distinct, generated_name
from symbiont.miner.incident_groups import (
    IncidentGroup,
    SessionDays,
    group_incidents,
    newest_first,
)
from symbiont.miner.incident_types import Incident, Outcome, Trigger
from symbiont.miner.incident_words import without_cd
from symbiont.miner.incidents import noise_words
from symbiont.miner.painpoint import Signal
from symbiont.miner.screen import ScreenRules
from symbiont.miner.story import working_on_line
from symbiont.miner.struggle import SessionFacts
from symbiont.miner.topics import TopicMap
from symbiont.service.dataset_history import dataset_readers
from symbiont.service.session_dates import session_dates_of
from symbiont.service.training_groups import trained_fingerprints
from symbiont.service.week_axis import sessions_per_week
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
# Outcomes where something really changed the result, so there is a fix a lesson can teach.
TEACHABLE_OUTCOMES = FIXED_OUTCOMES | {Outcome.CORRECTED_COMMAND}
MIN_RECURRING_SESSIONS = 2
SINGLE_CORRECTION = "One correction, on its own."


@dataclass(frozen=True)
class IncidentContext:
    """What the cards are told against: session titles and the session model's descriptions."""

    titles: Mapping[str, str] = field(default_factory=dict)
    topic_descriptions: Mapping[str, str] = field(default_factory=dict)
    correction_names: Mapping[tuple[str, int], str] = field(default_factory=dict)
    correction_descriptions: Mapping[str, str] = field(default_factory=dict)
    # Group keys whose mined lesson nightly training reads; see `training_groups`.
    trained: frozenset[str] = frozenset()
    # The session model's one-sentence verdict per group key; see `store.group_verdicts`.
    verdicts: Mapping[str, str] = field(default_factory=dict)
    # Sessions per ISO week over the whole project and its newest session day, for the badges.
    sessions_per_week: Sequence[Sequence[Any]] = ()
    latest_day: date | None = None
    # The session model's goal per session id, for "Working on"; see `store.session_summaries`.
    goals: Mapping[str, str] = field(default_factory=dict)


def incidents_snapshot(
    store: Store,
    project: str,
    rules: ScreenRules | None = None,
    only_sessions: frozenset[str] | None = None,
) -> dict[str, Any] | None:
    """The `incidents` data of `project`; None when sessions have no incident rows.

    `only_sessions` regroups from those sessions' cards, so every group field is theirs alone.
    """
    facts = store.mined.session_facts(project)
    mined = store.mined.incidents(project)
    if facts and not mined:
        return None
    if only_sessions is not None:
        mined = [card for card in mined if card.session_id in only_sessions]
    topic_map = store.review.summaries.topics(project)
    topic_of = {sid: g.name for g in topic_map.topics for sid in g.session_ids}
    cards = [replace(card, topic=topic_of.get(card.session_id, "")) for card in mined]
    trained = trained_fingerprints(store, project, rules or ScreenRules())
    days = {sid: when.isoformat() for sid, when in session_dates_of(facts).items()}
    shown = incident_groups(
        cards,
        days,
        _context_of(
            facts,
            topic_map,
            trained,
            store.review.verdicts.sentences(project),
            {s.session_id: s.goal for s in store.review.summaries.all(project)},
        ),
    )
    shown["ownHistory"] = not dataset_readers(store, project)
    return shown


def _context_of(
    facts: Sequence[SessionFacts],
    topic_map: TopicMap,
    trained: frozenset[str],
    verdicts: Mapping[str, str],
    goals: Mapping[str, str],
) -> IncidentContext:
    groups = topic_map.correction_groups
    return IncidentContext(
        {f.session_id: f.title for f in facts},
        {g.name: g.description for g in topic_map.topics},
        {ref: g.name for g in groups for ref in g.refs},
        {g.name: g.description for g in groups},
        trained,
        verdicts,
        goals=goals,
    )


def incident_groups(
    incidents: Sequence[Incident], days: SessionDays, context: IncidentContext | None = None
) -> dict[str, Any]:
    """Groups for the Inbox, cards by topic, and the noise with its reasons."""
    context = _with_session_axis(context or IncidentContext(), days)
    groups = group_incidents(incidents, days, context.correction_names)
    return {
        "groups": _named_apart(groups, [_group_json(g, days, context) for g in groups]),
        "topics": _topics(incidents, days, context),
        "noise": _noise_totals(incidents),
        "noTopic": [_ref(c, days) for c in newest_first(_worth(incidents, ""), days)],
        "sessionsPerWeek": [list(row) for row in context.sessions_per_week],
    }


def _named_apart(
    groups: Sequence[IncidentGroup], shown: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """`shown` with no two groups called the same: a repeat is told apart by where it happened."""
    places = [g.trigger.path if g.trigger else "" for g in groups]
    names = distinct([row["name"] for row in shown], places)
    return [{**row, "name": name} for row, name in zip(shown, names, strict=True)]


def _worth(incidents: Sequence[Incident], topic: str) -> list[Incident]:
    return [c for c in incidents if c.topic == topic and c.noise is None]


def _story(card: Incident, context: IncidentContext) -> dict[str, str]:
    """The card's story lines: the goal leads; cards stored before the lines fall back."""
    return {
        "workingOn": working_on_line(context.goals.get(card.session_id, ""), card.working_on, ""),
        "broke": card.broke or card.what_happened,
        "ended": card.ended or card.what_fixed_it,
    }


def _card(card: Incident, days: SessionDays, context: IncidentContext) -> dict[str, Any]:
    return {
        **_story(card, context),
        "happened": card.what_happened,
        "fixed": card.what_fixed_it,
        "outcome": card.outcome.value,
        "noise": card.noise.value if card.noise else None,
        "noiseWords": noise_words(card.noise) if card.noise else "",
        "date": days.get(card.session_id),
        "files": list(card.files),
        "sessionId": card.session_id,
        "firstWrong": card.first_wrong,
        "costSteps": card.cost_steps,
        "step": card.step,
        "command": card.example,
        "topic": card.topic,
        "session": context.titles.get(card.session_id, ""),
    }


def _ref(card: Incident, days: SessionDays) -> dict[str, Any]:
    """Where a card is listed (in its group); topics point at cards, never copy them."""
    return {"sessionId": card.session_id, "step": card.step, "date": days.get(card.session_id)}


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
        "worth": [_ref(c, days) for c in newest_first(_worth(incidents, name), days)],
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
        "name": generated_name(group),
        "title": without_cd(newest.example) or newest.what_happened,
        "groupedBecause": _grouped_because(group, context),
        "kind": "correction" if group.signal is Signal.CORRECTION else "failure",
        **_story(_card_behind_verdict(group.cards), context),
        "happened": newest.what_happened,
        "fixed": _fix_behind_verdict(group.cards),
        "fixShown": _dominant_outcome(group.cards) in TEACHABLE_OUTCOMES,
        "trains": group.signal is not Signal.CORRECTION and group.key in context.trained,
        "verdict": VERDICT_WORDS[_dominant_outcome(group.cards)],
        "verdictSentence": context.verdicts.get(group.key),
        "noise": group.noise.value if group.noise else None,
        "noiseWords": noise_words(group.noise) if group.noise else "",
        "sessions": len({c.session_id for c in group.cards}),
        "times": len(group.cards),
        "recurring": _recurring(group.cards),
        "weekly": weeks,
        "badge": _badge(group, weeks, days, context),
        "undated": undated,
        "undatedSessions": len({c.session_id for c in group.cards if not days.get(c.session_id)}),
        **_first_and_last(group.cards, days),
        "cards": [_card(c, days, context) for c in group.cards],
        "trigger": _trigger_json(group.trigger),
    }


def _recurring(cards: Sequence[Incident]) -> bool:
    """Seen in two or more sessions and nothing else: a one-session group is Seen once."""
    return len({c.session_id for c in cards}) >= MIN_RECURRING_SESSIONS


def _dominant_outcome(cards: Sequence[Incident]) -> Outcome:
    return Counter(c.outcome for c in cards).most_common(1)[0][0]


def _card_behind_verdict(cards: Sequence[Incident]) -> Incident:
    """The newest card whose outcome is the verdict's, so the story and the verdict agree."""
    outcome = _dominant_outcome(cards)
    return next(c for c in cards if c.outcome is outcome)


def _fix_behind_verdict(cards: Sequence[Incident]) -> str:
    """What fixed it, told by the card behind the verdict."""
    return _card_behind_verdict(cards).what_fixed_it


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
    return context.correction_descriptions.get(group.model_name) or (
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


def _with_session_axis(context: IncidentContext, days: SessionDays) -> IncidentContext:
    """`context` plus the sessions per week and newest session day that `days` imply."""
    known = [date.fromisoformat(day) for day in days.values() if day]
    return replace(
        context, sessions_per_week=sessions_per_week(known), latest_day=max(known, default=None)
    )


def _badge(
    group: IncidentGroup, weeks: list[list[Any]], days: SessionDays, context: IncidentContext
) -> str | None:
    first = _first_and_last(group.cards, days)["first"]
    return badge_of(
        weeks,
        context.sessions_per_week,
        date.fromisoformat(first) if first else None,
        context.latest_day,
    )
