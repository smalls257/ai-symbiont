"""Turns lost, the outcome of each failure, and the facts kept per session."""

from record_builders import edit, run, say, session, user
from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history
from symbiont.miner.struggle import (
    Outcome,
    SessionFacts,
    facts_of,
    turns_lost,
)
from symbiont.miner.themes import Codebase
from symbiont.records.session_tags import title_tag

CODE = Codebase(frozenset({"app"}))
FAIL = "Traceback\nValueError: no"


def test_turns_lost_is_zero_for_a_session_without_failures():
    assert turns_lost(session(run("pytest", 0), edit("app/a.py"), run("pytest", 0))) == 0


def test_turns_lost_counts_actions_from_a_failure_to_the_next_pass_of_the_same_program():
    steps = session(
        run("pytest", 1, FAIL), say("hmm"), edit("app/a.py"), run("pytest", 0), say("ok")
    )
    assert turns_lost(steps) == 4


def test_turns_lost_merges_overlapping_failure_spans():
    steps = session(
        run("pytest", 1, FAIL), say("a"), run("pytest", 1, FAIL), say("b"), run("pytest", 0)
    )
    assert turns_lost(steps) == 5


def test_a_failure_that_never_passes_is_capped_at_fifteen_turns():
    steps = session(run("pytest", 1, FAIL), *[say(str(n)) for n in range(40)])
    assert turns_lost(steps) == 16


def test_outcome_names_reuse_the_fix_kinds():
    assert Outcome.CODE_FIX.value == FixKind.CODE_FIX.value
    assert Outcome.CORRECTED_COMMAND.value == FixKind.CORRECTED_COMMAND.value


def facts_for(*records, vocabulary=frozenset({"parser"})):
    steps = session(*records)
    lessons = lessons_from(mine_history([steps], {}), steps, frozenset({"app"}))
    return facts_of([steps], lessons, CODE, vocabulary)


def test_facts_carry_themes_label_turns_and_outcomes_of_each_session():
    (facts,) = facts_for(
        user("the parser is broken", tags=(title_tag("Fix parser crash"),)),
        run("pytest tests/test_p.py", 1, "app/parser.py:3\nE   NameError: name 'x'"),
        edit("app/parser.py"),
        run("pytest tests/test_p.py", 0),
        run("ls nope", 2, "No such file"),
    )
    assert isinstance(facts, SessionFacts)
    assert facts.themes == {"parser"} and facts.task_label == "Fix parser crash"
    assert facts.turns_lost > 0 and facts.session_id == "s1"
    assert facts.outcomes[Outcome.CODE_FIX] == 1 and facts.outcomes[Outcome.PROBE] == 1


def test_a_failure_that_only_passed_when_respelled_is_not_counted_as_a_fix():
    (facts,) = facts_for(run("pytest tests/a.py", 1, FAIL), run("pytest tests/a.py -x", 0))
    assert Outcome.CODE_FIX not in facts.outcomes
    assert facts.outcomes[Outcome.RESPELLED] == 1


def test_a_session_with_three_failures_within_ten_steps_struggled():
    burst = [run(f"pytest t{n}", 1, FAIL) for n in range(3)]
    assert facts_for(*burst)[0].struggled
    assert not facts_for(burst[0], run("pytest", 0))[0].struggled
