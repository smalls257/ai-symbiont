"""Group rule candidates that say the same thing in different words, by shared terms.

Exact text never repeats, but "always use pnpm" and "use pnpm instead of npm" share `pnpm`.
Pure: candidates in, groups out.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.miner.rule_candidates import RuleCandidate

# Jaccard over distinctive terms. One shared term in two long rules is chance; a third of the
# union is the point where measured same-rule pairs sat above unrelated ones [hypothesis, not
# yet re-measured on a larger history].
MIN_TERM_JACCARD = 0.34
# A pair must share a term at all, so two candidates with no terms never merge.
MIN_SHARED_TERMS = 1


@dataclass(frozen=True)
class RuleGroup:
    """Candidates linked by shared terms; `key` is stable across re-mines."""

    key: str
    members: tuple[RuleCandidate, ...]
    terms: frozenset[str]


def group_by_terms(candidates: Sequence[RuleCandidate]) -> list[RuleGroup]:
    """Single-link merge: one close pair joins two candidates' groups, directly or by a chain."""
    ordered = sorted(candidates, key=_position)
    parent = list(range(len(ordered)))
    for later, candidate in enumerate(ordered):
        for earlier in range(later):
            if _same_rule(ordered[earlier], candidate):
                parent[_root(parent, later)] = _root(parent, earlier)
    buckets: dict[int, list[RuleCandidate]] = {}
    for index, candidate in enumerate(ordered):
        buckets.setdefault(_root(parent, index), []).append(candidate)
    return [_group(members) for members in buckets.values()]


def _position(candidate: RuleCandidate) -> tuple[str, int]:
    return (candidate.session_id, candidate.step)


def _same_rule(first: RuleCandidate, second: RuleCandidate) -> bool:
    shared = len(first.terms & second.terms)
    if shared < MIN_SHARED_TERMS:
        return False
    return shared / len(first.terms | second.terms) >= MIN_TERM_JACCARD


def _root(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _group(members: list[RuleCandidate]) -> RuleGroup:
    session_id, step = _position(members[0])
    terms = frozenset().union(*(member.terms for member in members))
    return RuleGroup(f"rule:{session_id}:{step}", tuple(members), terms)
