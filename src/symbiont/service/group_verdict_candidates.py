"""The groups still waiting for a verdict sentence, shaped for the session's model.

Only recurring, non-noise groups are offered: one-off failures and noise get no headline. The
examples are cards the page already holds (scrubbed), never raw history.
"""

from typing import Any

from symbiont.service.incident_view import incidents_snapshot
from symbiont.store.local import Store

MAX_GROUP_CANDIDATES = 40
EXAMPLES_PER_GROUP = 3


def group_candidates(store: Store, project: str) -> tuple[list[dict[str, Any]], int]:
    """Up to 40 candidate groups of `project` and how many more wait; groups come largest first."""
    shown = incidents_snapshot(store, project)
    written = store.review.verdicts.sentences(project)
    groups = [] if shown is None else shown["groups"]
    waiting = [row for row in groups if _needs_verdict(row, written)]
    waiting.sort(key=lambda row: (-row["sessions"], row["key"]))
    batch = waiting[:MAX_GROUP_CANDIDATES]
    return [_candidate(row) for row in batch], len(waiting) - len(batch)


def known_group_keys(store: Store, project: str) -> frozenset[str]:
    """The keys of every group on the Inbox, which a verdict may be written for."""
    shown = incidents_snapshot(store, project)
    return frozenset() if shown is None else frozenset(row["key"] for row in shown["groups"])


def _needs_verdict(group: dict[str, Any], written: dict[str, str]) -> bool:
    return bool(group["recurring"]) and group["noise"] is None and group["key"] not in written


def _candidate(group: dict[str, Any]) -> dict[str, Any]:
    keep = ("key", "name", "happened", "fixed", "verdict", "sessions", "times")
    return {name: group[name] for name in keep} | {
        "badge": group.get("badge"),
        "examples": [_example(c) for c in group["cards"][:EXAMPLES_PER_GROUP]],
    }


def _example(card: dict[str, Any]) -> dict[str, str]:
    return {
        "command": card.get("command", ""),
        "happened": card["happened"],
        "fixed": card["fixed"],
    }
