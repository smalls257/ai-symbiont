"""Group rule candidates that say the same thing in different words, by shared terms.

Exact text never repeats, but "always use pnpm" and "use pnpm instead of npm" share `pnpm`.
A candidate is compared with a group's seed only, never with any member, so a chain of
loosely related turns cannot grow one giant group. Pure: candidates in, groups out.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.miner.rule_candidates import RuleCandidate

# Jaccard over distinctive terms against the seed: a rule worded two ways in the real history
# (coderabbit toggling, 4 shared of 12) sat at 0.33, so the bar is 0.3 [hypothesis; re-measure
# on a larger history].
MIN_TERM_JACCARD = 0.3
# A pair must share a term at all, so two candidates with no terms never merge.
MIN_SHARED_TERMS = 1
# One distinctive shared term is chance in two long rules, so a single link needs half the union:
# "always use pnpm" and "use pnpm, not npm" group (0.5), a long turn naming pnpm once does not.
SINGLE_TERM_MIN_JACCARD = 0.5
# A term in more than this share of a project's candidates separates none of them ("commit",
# "file" in the 1,476 cipher-box candidates linked unrelated turns) [measured].
COMMON_SHARE = 0.03
# Below this count a term is never "common", so a handful of candidates keeps every term.
MIN_COMMON_COUNT = 8
# A group stops taking members here; the next close candidate seeds a new group, so no group is
# silently huge (the first real-data pass produced groups of 175 and 66).
MAX_GROUP_MEMBERS = 25


@dataclass(frozen=True)
class RuleGroup:
    """Candidates close to one seed; `key` is stable across re-mines."""

    key: str
    members: tuple[RuleCandidate, ...]
    terms: frozenset[str]


def group_by_terms(candidates: Sequence[RuleCandidate]) -> list[RuleGroup]:
    """Seed-based grouping in (session, step) order: join the first open group the seed matches."""
    ordered = sorted(candidates, key=_position)
    common = _common_terms(ordered)
    groups: list[list[RuleCandidate]] = []
    for candidate in ordered:
        target = _open_group_for(candidate, groups, common)
        if target is None:
            groups.append([candidate])
        else:
            groups[target].append(candidate)
    return [_group(members) for members in groups]


def _open_group_for(
    candidate: RuleCandidate, groups: list[list[RuleCandidate]], common: frozenset[str]
) -> int | None:
    for index, members in enumerate(groups):
        if len(members) < MAX_GROUP_MEMBERS and _same_rule(members[0], candidate, common):
            return index
    return None


def _common_terms(candidates: Sequence[RuleCandidate]) -> frozenset[str]:
    ceiling = max(MIN_COMMON_COUNT, COMMON_SHARE * len(candidates))
    seen = Counter(term for candidate in candidates for term in candidate.terms)
    return frozenset(term for term, count in seen.items() if count > ceiling)


def _position(candidate: RuleCandidate) -> tuple[str, int]:
    return (candidate.session_id, candidate.step)


def _same_rule(seed: RuleCandidate, other: RuleCandidate, common: frozenset[str]) -> bool:
    """Linked by a distinctive shared term; judged by the similarity of the whole term sets."""
    shared = (seed.terms & other.terms) - common
    if len(shared) < MIN_SHARED_TERMS:
        return False
    needed = SINGLE_TERM_MIN_JACCARD if len(shared) == 1 else MIN_TERM_JACCARD
    return len(seed.terms & other.terms) / len(seed.terms | other.terms) >= needed


def _group(members: list[RuleCandidate]) -> RuleGroup:
    session_id, step = _position(members[0])
    terms = frozenset().union(*(member.terms for member in members))
    return RuleGroup(f"rule:{session_id}:{step}", tuple(members), terms)
