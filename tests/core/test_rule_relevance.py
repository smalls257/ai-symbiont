"""Rules reach work they apply to, not only the exact failure that taught them.

Failures guarded against: a rule that never fires outside one failure signature (a Paper Tiger),
and a rule that fires on everything (noise that teaches the agent to ignore notes).
"""

from dataclasses import replace

from record_builders import edit, run, session
from symbiont.core.rule_relevance import paths_in, relevant_rules, rule_sentence, situation_terms
from symbiont.miner.lesson_context import LessonContext, Priority
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.trained import lesson_id

MONEY = 'File "src/billing/invoice.py", line 9\nE   assert 10.010000000000002 == 10.01'


def money_lesson():
    steps = session(
        run("pytest tests/test_invoice.py", 1, MONEY),
        edit("src/billing/invoice.py", diff="-a\n+cents\n"),
        run("pytest tests/test_invoice.py", 0, "1 passed"),
    )
    return lessons_from(mine_history(sessions_of(steps), {}), steps)[0]


RULE = "Money is stored in minor units; every refund and currency conversion rounds once."


def rules(**changes):
    lesson = money_lesson()
    words = LessonContext(RULE, **changes)
    return lesson, {lesson_id(lesson): words}


def test_work_on_the_lessons_own_file_is_related():
    lesson, contexts = rules()

    (match,) = relevant_rules("fix the build", ["src/billing/invoice.py"], [lesson], contexts)

    assert match.why.startswith("file: ")
    assert rule_sentence(match.words) == f"[symbiont] In this repo: {RULE.rstrip('.')}."


def test_a_sibling_module_in_the_same_area_is_related():
    lesson, contexts = rules()

    (match,) = relevant_rules("", ["src/billing/refund.py"], [lesson], contexts)

    assert match.why == "area: src/billing"


def test_a_test_file_named_for_the_module_is_related_but_a_generic_directory_is_not():
    lesson, contexts = rules()

    assert relevant_rules("", ["tests/test_invoice.py"], [lesson], contexts)
    assert not relevant_rules("", ["tests/test_other.py"], [lesson], contexts)
    assert not relevant_rules("", ["src/auth/login.py"], [lesson], contexts)


def test_shared_domain_words_make_a_rule_relevant_without_any_file():
    lesson, contexts = rules()

    (match,) = relevant_rules(
        "Add support for refunds in a second currency", [], [lesson], contexts
    )

    assert match.why.startswith("terms: ") and "currency" in match.why and "refund" in match.why


def test_one_shared_word_is_not_enough_and_unrelated_work_gets_nothing():
    lesson, contexts = rules()

    assert not relevant_rules("convert the currency flag to a string", [], [lesson], contexts)
    assert not relevant_rules(
        "rename the login button and update the readme", [], [lesson], contexts
    )


def test_intentional_or_wordless_lessons_are_never_rules():
    lesson, contexts = rules(intentional=True)
    assert not relevant_rules("", ["src/billing/invoice.py"], [lesson], contexts)

    wordless = {lesson_id(lesson): LessonContext("  ")}
    assert not relevant_rules("", ["src/billing/invoice.py"], [lesson], wordless)
    assert not relevant_rules("", ["src/billing/invoice.py"], [lesson], {})


def test_high_priority_rules_come_first():
    steps = session(
        run(
            "pytest tests/test_refund.py",
            1,
            'File "src/billing/refund.py", line 4\nE   assert 1 == 2',
        ),
        edit("src/billing/refund.py", diff="-a\n+b\n"),
        run("pytest tests/test_refund.py", 0, "1 passed"),
    )
    steps = [replace(step, session_id="s2") for step in steps]
    second = lessons_from(mine_history(sessions_of(steps), {}), steps)[0]
    first, contexts = rules()
    contexts[lesson_id(second)] = LessonContext("Never log card numbers.", priority=Priority.HIGH)

    ranked = relevant_rules("", ["src/billing/invoice.py"], [first, second], contexts)

    assert [m.words.priority for m in ranked] == [Priority.HIGH, Priority.NORMAL]


def test_paths_and_terms_are_extracted_from_free_text():
    assert paths_in("see src/a/b.py, and run test_x.py: ok") == ("src/a/b.py", "test_x.py")
    assert situation_terms("The Refunds are rounding") >= {"refund", "rounding"}
