"""Rules reach work they apply to, not only the exact failure that taught them.

Failures guarded against: a rule that never fires outside one failure signature (a Paper Tiger),
and a rule that fires on everything (noise that teaches the agent to ignore notes).
"""

from dataclasses import replace

from record_builders import edit, run, session
from symbiont.core.rule_relevance import (
    areas_of_files,
    lesson_files,
    paths_in,
    relevant_rules,
    rule_sentence,
    rules_of,
    situation_terms,
    why_none,
)
from symbiont.miner.lesson_context import (
    AppliesTo,
    AuthoredLesson,
    LessonContext,
    LessonKind,
    Priority,
    Severity,
)
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.trained import lesson_id

MONEY = 'File "src/billing/invoice.py", line 9\nE   assert 10.010000000000002 == 10.01'
RULE = "Money is stored in minor units; every refund and currency conversion rounds once."


def lesson_from(failing_output, fix_path, command="pytest tests/test_invoice.py", session_id="s1"):
    steps = session(
        run(command, 1, failing_output),
        edit(fix_path, diff="-a\n+cents\n"),
        run(command, 0, "1 passed"),
    )
    steps = [replace(step, session_id=session_id) for step in steps]
    return lessons_from(mine_history(sessions_of(steps), {}), steps, frozenset())[0]


def money_lesson():
    return lesson_from(MONEY, "src/billing/invoice.py")


def rules(**changes):
    lesson = money_lesson()
    contexts = {lesson_id(lesson): LessonContext(RULE, **changes)}
    return lesson, contexts, rules_of([lesson], contexts)


def ranked(text, files, rule_list, **extra):
    return relevant_rules(text, files, rule_list, **extra)


def test_work_on_the_lessons_own_file_is_related():
    _, _, rule_list = rules()

    (match,) = ranked("fix the build", ["src/billing/invoice.py"], rule_list)

    assert match.why.startswith("file: ")
    assert rule_sentence(match.rule.words) == f"[symbiont] In this repo: {RULE.rstrip('.')}."


def test_a_sibling_module_in_the_same_area_is_related():
    _, _, rule_list = rules()

    (match,) = ranked("", ["src/billing/refund.py"], rule_list)

    assert match.why == "area: src/billing (+3)"


def test_a_test_file_named_for_the_module_is_related_but_a_generic_directory_is_not():
    _, _, rule_list = rules()

    assert ranked("", ["tests/test_invoice.py"], rule_list)
    assert not ranked("", ["tests/test_other.py"], rule_list)
    assert not ranked("", ["src/auth/login.py"], rule_list)


def test_edits_between_failure_and_pass_are_the_lessons_files_though_the_error_names_none():
    lesson = lesson_from("E   assert 1 == 2", "src/billing/ledger.py", command="pytest -q")

    assert "src/billing/ledger.py" in lesson_files(lesson)


def test_shared_domain_words_make_a_rule_relevant_without_any_file():
    _, _, rule_list = rules()

    (match,) = ranked("Add support for refunds in a second currency conversion", [], rule_list)

    assert match.why == "words: conversion, currency, refund (+3)"


def test_one_shared_word_is_not_enough_and_unrelated_work_gets_nothing():
    _, _, rule_list = rules()

    assert not ranked("convert the currency flag to a string", [], rule_list)
    assert not ranked("rename the login button and update the readme", [], rule_list)


def test_intentional_or_wordless_lessons_are_never_rules():
    assert not rules(intentional=True)[2]
    lesson = money_lesson()
    assert not rules_of([lesson], {lesson_id(lesson): LessonContext("  ")})
    assert not rules_of([lesson], {})


def test_high_priority_rules_come_first():
    first, contexts, _ = rules()
    refund = 'File "src/billing/refund.py", line 4\nE   assert 1 == 2'
    second = lesson_from(refund, "src/billing/refund.py", "pytest tests/test_refund.py", "s2")
    contexts[lesson_id(second)] = LessonContext("Never log card numbers.", priority=Priority.HIGH)

    result = ranked("", ["src/billing/invoice.py"], rules_of([first, second], contexts))

    assert [m.rule.words.priority for m in result] == [Priority.HIGH, Priority.NORMAL]


def test_a_written_lesson_is_a_rule_with_its_severity_as_priority():
    written = AuthoredLesson(
        "a1",
        "Never retry a refund.",
        LessonKind.RULE,
        ("src/pay/refund.py",),
        "notes",
        Severity.HIGH,
    )
    rule_list = rules_of([], {}, [written])

    (match,) = ranked("touch src/pay/refund.py", [], rule_list)

    assert match.rule.words.priority is Priority.HIGH and match.rule.lesson is None


def test_focus_terms_rank_a_matching_rule_above_an_equal_one():
    first, contexts, _ = rules()
    other = lesson_from(MONEY, "src/billing/invoice.py", session_id="s2")
    contexts[lesson_id(other)] = LessonContext("Invoices are immutable once sent.")
    both = rules_of([first, other], contexts)

    result = ranked("", ["src/billing/invoice.py"], both, focus=frozenset({"money", "minor"}))

    assert "minor units" in result[0].rule.words.text


def test_the_miss_says_whether_the_lesson_has_no_files_or_the_files_are_unrelated():
    bare = lesson_from("E   assert 1 == 2", "notes.txt", command="pytest")
    bare_rules = rules_of([bare], {lesson_id(bare): LessonContext("Keep it small.")})
    _, _, filed = rules()

    assert "no files recorded" in why_none(bare_rules)
    assert "unrelated" in why_none(filed)


def test_paths_and_terms_are_extracted_from_free_text():
    assert paths_in("see src/a/b.py, and run test_x.py: ok") == ("src/a/b.py", "test_x.py")
    assert situation_terms("The Refunds are rounding") >= {"refund", "rounding"}


def tagged(text, terms=(), areas=()):
    written = AuthoredLesson(
        "t1", text, LessonKind.RULE, applies=AppliesTo(tuple(terms), tuple(areas))
    )
    return rules_of([], {}, [written])


def test_short_all_caps_codes_are_salient_terms():
    assert {"bhd", "jpy", "api"} <= situation_terms("price in BHD or JPY through the API")


def test_a_writers_tags_make_a_rule_relevant_when_the_rule_text_shares_no_words():
    rule_list = tagged(
        "Amounts are integers in minor units.",
        terms=["currency", "BHD", "credit note", "proration"],
    )

    (match,) = ranked("Handle the BHD credit note in the new billing flow", [], rule_list)

    assert "bhd" in match.why and "credit note" in match.why


def test_one_tag_fires_with_its_weight_and_a_phrase_needs_all_its_words():
    rule_list = tagged("Amounts are integers.", terms=["credit note", "BHD"])

    (match,) = ranked("write a note about the BHD", [], rule_list)

    assert match.why == "tag: bhd (+3)"
    assert not ranked("add a credit limit for the team", [], rule_list)


def test_an_area_tag_matches_any_path_under_the_prefix():
    rule_list = tagged("Ledger writes are append-only.", areas=["ledger/"])

    (match,) = ranked("", ["src/ledger/entries.py"], rule_list)

    assert match.why.startswith("area tag: ledger/ (+3)")
    assert not ranked("", ["src/ledgerish/x.py"], rule_list)


DJANGO_RULE = (
    "The sqlite schema editor skipped the table remake because the other field changed only "
    "its choices, so no SQL ran."
)


def django_rules():
    return tagged(
        DJANGO_RULE,
        terms=["choices", "_field_should_be_altered", "non_database_attrs"],
        areas=["alter_field", "sqlite schema editor"],
    )


def test_generic_words_alone_do_not_fire_a_tagged_lesson():
    prompt = "The other table has a field, because sql in sqlite fails"

    assert not ranked(prompt, [], django_rules())


def test_the_lessons_own_tag_or_area_fires_it_and_the_event_names_the_signals():
    (by_term,) = ranked("Why does non_database_attrs ignore this?", [], django_rules())
    (by_area,) = ranked("review alter_field for the sqlite schema editor", [], django_rules())

    assert by_term.why == "tag: non_database_attrs (+3)"
    assert by_area.why.startswith("area tag: alter_field (+3)")


def test_a_lesson_with_no_tags_still_fires_on_its_file_or_area():
    _, _, rule_list = rules()

    assert ranked("", ["src/billing/invoice.py"], rule_list)
    assert ranked("", ["src/billing/other.py"], rule_list)
    assert not ranked("the other table, because of the field", [], rule_list)


def test_the_ledger_rule_fires_on_its_codes_and_minor_units_but_not_one_code_alone():
    rule_list = tagged("BHD and JPY amounts are integers in minor units.")

    (match,) = ranked("round the BHD amount in minor units", [], rule_list)

    assert match.why == "identifiers: bhd (+2); words: amount, minor, units (+3)"
    assert not ranked("print the BHD", [], rule_list)


def test_identifier_like_tokens_are_distinctive_and_generic_words_are_not_terms():
    assert {"alter_field", "djangomodel", "db.schema"} <= situation_terms(
        "alter_field DjangoModel db.schema"
    )
    assert not situation_terms("because other field table file test error value")


def test_words_most_lessons_share_count_for_nothing():
    names = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    texts = [f"Billing invoices refund {name}." for name in names]
    written = [AuthoredLesson(f"w{i}", text, LessonKind.RULE) for i, text in enumerate(texts)]
    rule_list = rules_of([], {}, written)

    assert not ranked("billing invoices refund", [], rule_list)
    assert not ranked("billing invoices refund alpha", [], rule_list)
    assert len(ranked("billing invoices refund alpha", [], rule_list[:3])) == 3


def written(ident, text, files, **extra):
    return AuthoredLesson(ident, text, LessonKind.RULE, tuple(files), **extra)


ARRAY = "pkg/tensor/array/expressions"


def test_a_lesson_about_one_file_reaches_work_on_a_sibling_in_the_same_module_directory():
    rule_list = rules_of(
        [],
        {},
        [written("a", "Hadamard power goes through HadamardPower.", [f"{ARRAY}/to_matrix.py"])],
    )

    (match,) = ranked("", [f"{ARRAY}/from_indexed.py"], rule_list)

    assert match.why == f"area: {ARRAY} (+3)"


def test_the_lessons_own_file_outranks_a_sibling_lesson():
    own = written("own", "Own file rule.", [f"{ARRAY}/to_matrix.py"])
    sibling = written("sib", "Sibling file rule.", [f"{ARRAY}/other.py"])

    found = ranked("", [f"{ARRAY}/to_matrix.py"], rules_of([], {}, [sibling, own]))

    assert [m.rule.ident for m in found] == ["own", "sib"]
    assert found[0].strength > found[1].strength


def test_generic_directories_and_bare_names_are_never_a_module_area():
    assert areas_of_files(["src/a.py", "tests/b.py", "c.py", "./d.py"]) == ()
    assert areas_of_files([f"{ARRAY}/a.py", f"{ARRAY}/b.py", "src/x/c.py"]) == (ARRAY, "src/x")
    rule_list = rules_of([], {}, [written("a", "Rule about a.", ["src/a.py"])])

    assert not ranked("", ["src/b.py"], rule_list)


def test_a_long_rule_is_cut_at_a_word_for_the_note():
    words = LessonContext("word " * 200)

    sentence = rule_sentence(words)

    assert len(sentence) < 640 and sentence.endswith(" ...")


def test_a_typical_348_char_lesson_is_delivered_whole():
    lesson = "Guard scalar bases to return plain Pow, " + "and route array bases " * 14
    assert 340 < len(lesson) < 400

    sentence = rule_sentence(LessonContext(lesson))

    assert sentence == f"[symbiont] In this repo: {lesson.strip()}."


def test_an_over_long_rule_is_cut_at_a_sentence_end_not_mid_sentence():
    first = "Keep ledger writes append only and never edit a posted row."
    words = LessonContext(" ".join([first] * 20))

    sentence = rule_sentence(words)

    assert sentence.endswith(first + " ...") and len(sentence) < 640


def test_an_over_long_rule_without_sentence_ends_is_cut_at_a_clause():
    words = LessonContext("keep the ledger append only, " * 40)

    sentence = rule_sentence(words)

    assert sentence.endswith("append only ...") and len(sentence) < 640
