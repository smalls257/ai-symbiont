"""The `rules` key of the dashboard data: what the developer told the agent more than once.

A confirmed rule (the session model merged what was said) is shown as the model wrote it. Groups
of two or more messages that share distinctive words, and that no confirmed rule or drop covers,
are listed too, marked unconfirmed. A dismissal or a teach follows the rule's member messages (a
majority of them), not only its key, because grouping can rename a group when an earlier session
is mined. Quotes are scrubbed here again.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
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
    members: Mapping[str, frozenset[Ref]] = field(default_factory=dict)


def rules_listing(store: Store, project: str, dates: Mapping[str, date]) -> dict[str, Any]:
    """The snapshot's `rules` for `project`."""
    triage = store.review.triage.all(project)
    triaged = Triaged(
        [key for key, row in triage.items() if row.state is GroupState.ARCHIVED],
        [key for key, row in triage.items() if row.taught_on is not None],
        store.review.triage.members_by_key(project),
    )
    candidates = store.mined.rule_candidates(project)
    return rules_snapshot(_current(store, project, candidates), candidates, dates, triaged)


def member_refs(store: Store, project: str, key: str) -> tuple[Ref, ...]:
    """The messages the rule `key` stands for now; () when no rule has that key any more."""
    entries = _current(store, project, store.mined.rule_candidates(project))
    return next((entry.refs for entry in entries if entry.key == key), ())


def _current(store: Store, project: str, candidates: Sequence[RuleCandidate]) -> list[RuleEntry]:
    rules = store.review.rules
    return rule_entries(rules.rules(project), candidates, rules.covered(project))


def rule_entries(
    rules: Sequence[StatedRule],
    candidates: Sequence[RuleCandidate],
    covered: Collection[Ref] = (),
) -> list[RuleEntry]:
    """The confirmed rules, then term groups of two or more messages no rule or drop covers."""
    confirmed = [
        RuleEntry(r.key, r.rule, r.scope.value, r.area, tuple(sorted(r.refs)), confirmed=True)
        for r in rules
    ]
    open_candidates = [c for c in candidates if (c.session_id, c.step) not in covered]
    groups = [g for g in group_by_terms(open_candidates) if len(g.members) >= MIN_GROUP_MEMBERS]
    guesses = [
        RuleEntry(g.key, _clearest(g.members), "repo", "", _refs(g.members), confirmed=False)
        for g in groups
    ]
    return confirmed + guesses


def rules_snapshot(
    entries: Sequence[RuleEntry],
    candidates: Sequence[RuleCandidate],
    dates: Mapping[str, date],
    triaged: Triaged,
) -> dict[str, Any]:
    """Items most-repeated first, dismissed rules counted and left out, taught ones marked."""
    said = {(c.session_id, c.step): c for c in candidates}
    items: list[dict[str, Any]] = []
    dismissed = {True: 0, False: 0}
    for entry in entries:
        state = triage_outcome(entry, triaged)
        if state is None:
            dismissed[entry.confirmed] += 1
        else:
            items.append(_item(entry, state, said, dates))
    items.sort(key=lambda item: item["key"])
    items.sort(key=lambda item: item["last"] or "", reverse=True)
    items.sort(key=lambda item: item["sessions"], reverse=True)
    return {
        "confirmed": any(entry.confirmed for entry in entries),
        "items": items,
        "dismissed": dismissed[True],
        "dismissedPossible": dismissed[False],
    }


def triage_outcome(entry: RuleEntry, triaged: Triaged) -> str | None:
    """None when dismissed, TAUGHT when taught, else NEW; dismissal outranks a teach.

    A rule matches a triaged one by key, or when most of its messages were that rule's, so a
    group renamed by an earlier session is the same rule but one shared message is not.
    """
    for keys, outcome in ((triaged.dismissed, None), (triaged.taught, TAUGHT)):
        if entry.key in keys or _mostly_from(entry, keys, triaged.members):
            return outcome
    return NEW


def _mostly_from(
    entry: RuleEntry, keys: Collection[str], members: Mapping[str, frozenset[Ref]]
) -> bool:
    earlier = frozenset().union(*(members.get(key, frozenset()) for key in keys))
    return 2 * len(earlier & set(entry.refs)) > len(entry.refs)


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
