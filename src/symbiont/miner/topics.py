"""Validate the topic map the developer's session model returns for all summarized sessions.

A session missing from every topic, or counted in two, would silently skew every per-topic
number on the dashboard, so the map is refused naming the ids.
Frictions and correction groups are optional groupings; topics are a partition of the sessions
that are not noise. Pure: a payload and the summaries in, a checked map or `TopicMapError` out.
"""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from symbiont.miner.secrets import scrub
from symbiont.miner.session_summary import SessionSummary

# Word ranges from the failure-cards plan (Task 8). "Other" is the one allowed single word:
# the plan lets a leftover topic exist so every session can be placed.
TOPIC_WORDS = (2, 4)
GROUP_WORDS = (2, 5)
CATCH_ALL = "Other"
MAX_DESCRIPTION_CHARS = 300
MAP_KEYS = frozenset({"topics", "frictions", "correction_groups"})


class TopicMapError(ValueError):
    """A topic map that breaks a rule; the message names the field or the session ids."""


@dataclass(frozen=True)
class Group:
    """A named set of sessions: a topic or a friction category."""

    name: str
    description: str
    session_ids: tuple[str, ...]


@dataclass(frozen=True)
class CorrectionGroup:
    """What the developer keeps asking for: corrections as (session id, step) pairs."""

    name: str
    description: str
    refs: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class TopicMap:
    """Topics, friction categories and correction groups for one project."""

    topics: tuple[Group, ...]
    frictions: tuple[Group, ...]
    correction_groups: tuple[CorrectionGroup, ...]


def topic_map_from(
    payload: Mapping[str, Any],
    summaries: Sequence[SessionSummary],
    offered_refs: Collection[tuple[str, int]],
) -> TopicMap:
    """The checked, scrubbed map; `offered_refs` are the (session, step) corrections shown.

    Raises TopicMapError when a session is missing, doubled or unknown, or a ref was not offered.
    """
    extra = set(payload) - MAP_KEYS
    if extra or "topics" not in payload:
        raise TopicMapError(
            f"expected topics, frictions and correction_groups; got {sorted(extra)}"
        )
    known = {item.session_id for item in summaries}
    topics = _groups(payload["topics"], "topics", TOPIC_WORDS, known, allow_catch_all=True)
    frictions = _groups(payload.get("frictions", []), "frictions", GROUP_WORDS, known)
    groups = _correction_groups(payload.get("correction_groups", []), known, set(offered_refs))
    _require_partition(topics, {item.session_id for item in summaries if not item.noise})
    return TopicMap(topics, frictions, groups)


def _groups(
    value: Any,
    field: str,
    words: tuple[int, int],
    known: set[str],
    *,
    allow_catch_all: bool = False,
) -> tuple[Group, ...]:
    result = []
    for item in _objects(value, field):
        name = _name(item, field, words, allow_catch_all=allow_catch_all)
        ids = _strings(item.get("session_ids"), f"{field} session_ids")
        _require_known(ids, known)
        result.append(Group(name, _description(item, field), ids))
    return tuple(result)


def _correction_groups(
    value: Any, known: set[str], offered: set[tuple[str, int]]
) -> tuple[CorrectionGroup, ...]:
    result = []
    for item in _objects(value, "correction_groups"):
        name = _name(item, "correction_groups", GROUP_WORDS, allow_catch_all=False)
        refs = tuple(_ref(ref) for ref in _objects_or_lists(item.get("refs")))
        _require_known(tuple(session for session, _ in refs), known)
        _require_offered(refs, offered)
        result.append(CorrectionGroup(name, _description(item, "correction_groups"), refs))
    return tuple(result)


def _ref(ref: Any) -> tuple[str, int]:
    ok = len(ref) == 2 and isinstance(ref[0], str) and type(ref[1]) is int
    if not ok:
        raise TopicMapError("each correction ref must be [session_id, step]")
    return ref[0], ref[1]


def _objects_or_lists(value: Any) -> list[Any]:
    if not isinstance(value, list) or not all(isinstance(ref, list) for ref in value):
        raise TopicMapError("refs must be a list of [session_id, step] pairs")
    return value


def _objects(value: Any, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TopicMapError(f"{field} must be a list of objects")
    return value


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TopicMapError(f"{field} must be a list of session ids")
    return tuple(value)


def _name(
    item: Mapping[str, Any], field: str, words: tuple[int, int], *, allow_catch_all: bool
) -> str:
    name = item.get("name")
    if not isinstance(name, str):
        raise TopicMapError(f"each of {field} needs a name")
    name = name.strip()
    if allow_catch_all and name == CATCH_ALL:
        return name
    low, high = words
    if not low <= len(name.split()) <= high:
        raise TopicMapError(f"a name in {field} must be {low} to {high} words: {name!r}")
    return scrub(name)


def _description(item: Mapping[str, Any], field: str) -> str:
    text = item.get("description", "")
    if not isinstance(text, str) or not text.strip():
        raise TopicMapError(f"each of {field} needs a description")
    return scrub(text.strip())[:MAX_DESCRIPTION_CHARS]


def _require_offered(refs: Sequence[tuple[str, int]], offered: set[tuple[str, int]]) -> None:
    unknown = sorted(f"{session}:{step}" for session, step in set(refs) - offered)
    if unknown:
        raise TopicMapError(f"unknown corrections (not offered): {', '.join(unknown)}")


def _require_known(ids: Sequence[str], known: set[str]) -> None:
    unknown = sorted(set(ids) - known)
    if unknown:
        raise TopicMapError(f"unknown session ids (not summarized): {', '.join(unknown)}")


def _require_partition(topics: Sequence[Group], expected: set[str]) -> None:
    """Every expected session is in exactly one topic."""
    seen = Counter(ident for topic in topics for ident in topic.session_ids)
    missing = sorted(expected - set(seen))
    doubled = sorted(ident for ident, count in seen.items() if count > 1)
    if missing or doubled:
        parts = [f"missing: {', '.join(missing)}"] if missing else []
        parts += [f"placed twice: {', '.join(doubled)}"] if doubled else []
        raise TopicMapError("every session needs exactly one topic; " + "; ".join(parts))
