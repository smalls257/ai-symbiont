from dataclasses import replace

from record_builders import session, user
from symbiont.miner.rule_candidates import RuleCandidate, find_rule_candidates, rule_terms
from symbiont.miner.rule_groups import MAX_GROUP_MEMBERS, group_by_terms


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


def terms_of(sid, step, text):
    return RuleCandidate(sid, step, text, rule_terms(text), "rule_words")


def test_terse_and_polite_wordings_of_one_rule_group():
    found = (
        candidates("always use pnpm", sid="b")
        + candidates("use pnpm, not npm please", sid="a")
        + candidates("don't use npm", sid="c")
    )
    (group,) = group_by_terms(found)
    assert [m.session_id for m in group.members] == ["a", "b", "c"]


def test_chained_turns_do_not_form_one_group():
    chain = [
        terms_of("s", 0, "never touch alpha beta"),
        terms_of("s", 1, "never touch beta gamma"),
        terms_of("s", 2, "never touch gamma delta"),
        terms_of("s", 3, "never touch delta epsilon"),
    ]
    groups = group_by_terms(chain)
    assert max(len(g.members) for g in groups) < len(chain)


def test_a_term_in_many_candidates_links_nothing():
    crowd = [terms_of("s", i, f"never mention widget in topic{chr(97 + i)}") for i in range(12)]
    assert len(group_by_terms(crowd)) == 12


def test_groups_are_capped():
    crowd = [terms_of("a", i, f"never touch {_word(i)}") for i in range(1200)]
    same = [terms_of("z", i, "always use pnpm") for i in range(MAX_GROUP_MEMBERS + 5)]
    sizes = sorted(len(g.members) for g in group_by_terms(crowd + same))
    assert sizes[-1] == MAX_GROUP_MEMBERS and sizes[-2] == 5


def _word(number):
    """A distinct all-letter word per number, so no term repeats across candidates."""
    letters = "abcdefghij"
    return "w" + "".join(letters[int(digit)] for digit in str(number)) + "q"


def test_coderabbit_turns_group_and_commit_turns_stay_apart():
    toggle = terms_of(
        "a",
        1,
        "please remember to toggle to ready, wait a bit and then toggle back to draft, "
        "to ensure that coderabbit reviews every change",
    )
    drive = terms_of(
        "b",
        1,
        "ok, I am AFK, please drive the coderabbit reviews one at a time, "
        "ideally by toggling draft/ready",
    )
    retry = terms_of("c", 1, "sorry please try commit now - i was afk")
    unlock = terms_of("d", 1, "please retry the git commit, I will unlock 1pass")
    extra = terms_of("e", 1, "please commit the debug file as well")
    groups = group_by_terms([toggle, drive, retry, unlock, extra])
    held = {m.session_id: g.key for g in groups for m in g.members}
    assert held["a"] == held["b"]
    assert held["e"] not in (held["c"], held["d"])
    assert held["e"] != held["a"]
