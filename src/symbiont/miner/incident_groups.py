"""Incident groups: cards that are the same trouble, so the Inbox shows it once.

Why this exists: a failure that happens thirty times is one thing to review, not thirty. A group's
key comes from what the cards are about (never from their order), so a re-mine keeps the key and
the developer's triage stays attached. Pure: dates and the correction groups are passed in.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from symbiont.miner.incident_types import Incident, NoiseReason, Trigger
from symbiont.miner.incidents import trigger_of
from symbiont.miner.painpoint import Signal

EMPTY_CORRECTIONS = "correction:empty"

# (session id, step) -> the name of the correction group the developer's session model made.
CorrectionNames = Mapping[tuple[str, int], str]
# Session id -> ISO day, or None for a session with no timestamps.
SessionDays = Mapping[str, str | None]


@dataclass(frozen=True)
class IncidentGroup:
    """Cards that share a fingerprint, newest first, and what they imply together."""

    key: str
    signal: Signal
    cards: tuple[Incident, ...]
    noise: NoiseReason | None  # set only when every card is noise
    trigger: Trigger | None


def fingerprint_of(card: Incident, corrections: CorrectionNames) -> str:
    """A failure's (program, what broke); a correction's model group, else its own."""
    if card.signal is not Signal.CORRECTION:
        return card.fingerprint
    if card.noise is NoiseReason.EMPTY_CORRECTION:
        return EMPTY_CORRECTIONS
    named = corrections.get((card.session_id, card.step))
    if named is not None:
        return f"correction:{named}"
    return f"correction:{card.session_id}:{card.step}"


def group_incidents(
    incidents: Sequence[Incident], days: SessionDays, corrections: CorrectionNames
) -> list[IncidentGroup]:
    """One group per fingerprint, the one with the most cards first."""
    by_key: dict[str, list[Incident]] = {}
    for card in incidents:
        by_key.setdefault(fingerprint_of(card, corrections), []).append(card)
    groups = [_group(key, cards, days) for key, cards in by_key.items()]
    return sorted(groups, key=lambda group: (-len(group.cards), group.key))


def newest_first(cards: Sequence[Incident], days: SessionDays) -> tuple[Incident, ...]:
    """Dated cards newest first, then the undated ones; ties keep session and step order."""
    ordered = sorted(cards, key=lambda card: (card.session_id, card.step))
    dated = [card for card in ordered if days.get(card.session_id)]
    dated.sort(key=lambda card: days[card.session_id] or "", reverse=True)
    return tuple(dated + [card for card in ordered if not days.get(card.session_id)])


def _group(key: str, cards: Sequence[Incident], days: SessionDays) -> IncidentGroup:
    ordered = newest_first(cards, days)
    return IncidentGroup(
        key, ordered[0].signal, ordered, _shared_noise(ordered), trigger_of(ordered)
    )


def _shared_noise(cards: Sequence[Incident]) -> NoiseReason | None:
    reasons = [card.noise for card in cards]
    if any(reason is None for reason in reasons):
        return None
    return Counter(reasons).most_common(1)[0][0]
