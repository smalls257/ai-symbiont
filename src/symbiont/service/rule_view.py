"""The `rules` key of the dashboard data: what the developer told the agent more than once.

A confirmed rule (the session model merged what was said) is shown as the model wrote it. Until
one exists, groups of two or more messages that share distinctive words are shown instead, marked
unconfirmed. A dismissal or a teach follows the rule's member messages, not only its key, because
grouping can rename a group when an earlier session is mined. Quotes are scrubbed here again.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from symbiont.core.triage import GroupState
from symbiont.miner.credential_patterns import scrub
from symbiont.miner.rule_candidates import RuleCandidate
from symbiont.miner.rule_groups import group_by_terms
from symbiont.miner.stated_rule import Ref, StatedRule
from symbiont.store.local import Store

MAX_QUOTE_CHARS = 120
MAX_EXAMPLES = 3
# A group of one message is a single remark, not something said more than once [hypothesis].
MIN_GROUP_MEMBERS = 2
NEW, TAUGHT = "new", "taught"


@dataclass(frozen=True)
class RuleEntry:
    """One rule before triage: its words, where it applies and the messages behind it."""

    key: str
    text: str
    scope: str
    area: str
    refs: tuple[Ref, ...]
    confirmed: bool = False


@dataclass(frozen=True)
class Triaged:
    """The developer's choices: keys dismissed or taught, and the messages those rules stood for."""

    dismissed: Collection[str] = ()
    taught: Collection[str] = ()
    members: Mapping[str, frozenset[Ref]] | None = None


def rules_listing(store: Store, project: str, dates: Mapping[str, date]) -> dict[str, Any]:
    """The snapshot's `rules` for `project`."""
    triage = store.review.triage.all(project)
    triaged = Triaged(
        [key for key, row in triage.items() if row.state is GroupState.ARCHIVED],
        [key for key, row in triage.items() if row.taught_on is not None],
        store.review.rules.members_by_key(project),
    )
    candidates = store.mined.rule_candidates(project)
    entries = rule_entries(store.review.rules.rules(project), candidates)
    return rules_snapshot(entries, candidates, dates, triaged)


def member_refs(store: Store, project: str, key: str) -> tuple[Ref, ...]:
    """The messages the rule `key` stands for now; () when no rule has that key any more."""
    entries = rule_entries(store.review.rules.rules(project), store.mined.rule_candidates(project))
    return next((entry.refs for entry in entries if entry.key == key), ())


def rule_entries(
    rules: Sequence[StatedRule], candidates: Sequence[RuleCandidate]
) -> list[RuleEntry]:
    """The confirmed rules when any exist, else the term groups with two or more messages."""
    if rules:
        return [
            RuleEntry(r.key, r.rule, r.scope.value, r.area, tuple(sorted(r.refs)), confirmed=True)
            for r in rules
        ]
    groups = [g for g in group_by_terms(candidates) if len(g.members) >= MIN_GROUP_MEMBERS]
    return [
        RuleEntry(g.key, _clearest(g.members), "repo", "", _refs(g.members), confirmed=False)
        for g in groups
    ]


def rules_snapshot(
    entries: Sequence[RuleEntry],
    candidates: Sequence[RuleCandidate],
    dates: Mapping[str, date],
    triaged: Triaged,
) -> dict[str, Any]:
    """Items most-repeated first, dismissed rules counted and left out, taught ones marked."""
    said = {(c.session_id, c.step): c for c in candidates}
    items, dismissed = [], 0
    for entry in entries:
        state = _state(entry, triaged)
        if state is None:
            dismissed += 1
        else:
            items.append(_item(entry, state, said, dates))
    items.sort(key=lambda item: item["key"])
    items.sort(key=lambda item: item["last"] or "", reverse=True)
    items.sort(key=lambda item: item["sessions"], reverse=True)
    return {
        "confirmed": any(entry.confirmed for entry in entries),
        "items": items,
        "dismissed": dismissed,
    }


def _state(entry: RuleEntry, triaged: Triaged) -> str | None:
    """None when dismissed (by key or by any member message), TAUGHT, else NEW."""
    refs = set(entry.refs)
    members = triaged.members or {}
    for keys, outcome in ((triaged.dismissed, None), (triaged.taught, TAUGHT)):
        hit = entry.key in keys or any(refs & members.get(key, frozenset()) for key in keys)
        if hit:
            return outcome
    return NEW


def _item(
    entry: RuleEntry,
    state: str,
    said: Mapping[Ref, RuleCandidate],
    dates: Mapping[str, date],
) -> dict[str, Any]:
    days = sorted(dates[sid] for sid, _ in entry.refs if sid in dates)
    return {
        "key": entry.key,
        "text": _quote(entry.text),
        "confirmed": entry.confirmed,
        "scope": entry.scope,
        "area": _quote(entry.area),
        "times": len(entry.refs),
        "sessions": len({sid for sid, _ in entry.refs}),
        "first": days[0].isoformat() if days else None,
        "last": days[-1].isoformat() if days else None,
        "examples": _examples(entry, said, dates),
        "state": state,
    }


def _examples(
    entry: RuleEntry, said: Mapping[Ref, RuleCandidate], dates: Mapping[str, date]
) -> list[dict[str, Any]]:
    """Up to three quotes, newest first; undated ones last."""
    found = [said[ref] for ref in entry.refs if ref in said]
    found.sort(key=lambda hit: (_day(hit, dates), hit.session_id, hit.step), reverse=True)
    return [
        {
            "text": _quote(c.text),
            "sessionId": c.session_id,
            "step": c.step,
            "date": dates[c.session_id].isoformat() if c.session_id in dates else None,
        }
        for c in found[:MAX_EXAMPLES]
    ]


def _day(candidate: RuleCandidate, dates: Mapping[str, date]) -> date:
    return dates.get(candidate.session_id, date.min)


def _clearest(members: Sequence[RuleCandidate]) -> str:
    """The shortest member quote: the least padded way the developer said it."""
    return min((m.text for m in members), key=lambda text: (len(text), text))


def _refs(members: Sequence[RuleCandidate]) -> tuple[Ref, ...]:
    return tuple(sorted((m.session_id, m.step) for m in members))


def _quote(text: str) -> str:
    """One line, credential-free, capped: scrubbed at the moment it enters the snapshot."""
    return " ".join(scrub(text).split())[:MAX_QUOTE_CHARS]
