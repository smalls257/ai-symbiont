from dataclasses import replace

from record_builders import session, user
from symbiont.miner.rule_candidates import RuleCandidate, find_rule_candidates
from symbiont.miner.rule_groups import group_by_terms


def candidates(*turns: str, sid="s1") -> list[RuleCandidate]:
    records = [replace(r, session_id=sid) for r in session(*(user(t) for t in turns))]
    return find_rule_candidates(records)


def test_package_manager_rules_group_apart_from_test_rules():
    found = (
        candidates("always use pnpm, never npm")
        + candidates("use pnpm instead of npm for installs", sid="s2")
        + candidates("always run pytest before committing", sid="s3")
    )
    groups = group_by_terms(found)
    sizes = sorted(len(g.members) for g in groups)
    assert sizes == [1, 2]
    pnpm = next(g for g in groups if len(g.members) == 2)
    assert {"pnpm", "npm"} <= pnpm.terms


def test_one_shared_term_is_not_enough_when_the_rest_differs():
    found = candidates(
        "never commit generated files under dist", "avoid mocking the database in integration tests"
    )
    assert len(group_by_terms(found)) == 2


def test_key_is_smallest_member_and_stable_when_reordered():
    found = candidates("always use pnpm, never npm") + candidates(
        "prefer pnpm instead of npm", sid="a0"
    )
    forward = group_by_terms(found)
    backward = group_by_terms(list(reversed(found)))
    assert [g.key for g in forward] == [g.key for g in backward] == ["rule:a0:0"]
    assert forward[0].members == backward[0].members


def test_candidates_without_terms_never_merge():
    empty = [RuleCandidate("s1", i, "never", frozenset(), "rule_words") for i in range(2)]
    assert len(group_by_terms(empty)) == 2
