"""A PR lesson with the reviewer's words says them first and whole, at the cap and in house rules.

Failures guarded against: Forensic Coding (a maintainer's general ruling delivered as a narrower
paraphrase, which 4 of 4 runs ignored) and Paper Tiger (a quote stored but never delivered).
All text is synthetic.
"""

from symbiont.core.house_rules import LEAD, standing_corrections, standing_sentence
from symbiont.core.quoted_rule import rule_note
from symbiont.core.rule_relevance import MAX_NOTE_CHARS, file_scoped_rules, rules_of
from symbiont.miner.lesson_context import AuthoredLesson, LessonKind
from symbiont.miner.review_quote import MAX_QUOTE_CHARS, capped_at_sentence, pull_number

URL = "https://github.com/acme/shop/pull/7396"
QUOTE = "Don't copy expressions in generator code; the generator already copies the whole tree."
LESSON = "Do not copy properties inside the ledger sub-method."


def rule_of(text=LESSON, quote=QUOTE, role="maintainer", kind=LessonKind.RULE, url=URL):
    item = AuthoredLesson(
        "w-1", text, kind, ("src/ledger/gen.py",), source_url=url, quote=quote, quote_role=role
    )
    return rules_of([], {}, [item])[0]


def test_a_quoted_note_puts_the_reviewers_words_first_then_the_lesson_in_parentheses():
    assert rule_note(rule_of()) == (
        f'[symbiont] In this repo, a maintainer said on PR #7396: "{QUOTE}" ({LESSON.rstrip(".")}).'
    )


def test_a_rule_without_a_quote_reads_as_before():
    note = rule_note(rule_of(quote="", role=""))

    assert note == f"[symbiont] In this repo: {LESSON.rstrip('.')}."


def test_a_quote_with_no_pull_request_to_cite_is_not_said():
    assert "said on PR" not in rule_note(rule_of(url=""))


def test_the_lesson_gives_way_before_the_quote_at_the_note_cap():
    quote = ("Never copy expressions here. " * 10).strip()[:MAX_QUOTE_CHARS]
    quote = capped_at_sentence(quote)
    long_lesson = "Keep the tree uncopied in every generator. " * 20

    note = rule_note(rule_of(text=long_lesson, quote=quote))

    assert f'"{quote}"' in note
    assert len(note) <= MAX_NOTE_CHARS and note.endswith(").")
    assert note.count("Keep the tree uncopied") < 20


def test_a_lesson_that_cannot_fit_beside_the_quote_is_left_out_not_cut_midway():
    quote = ("Never copy expressions in generators. " * 8).strip()
    quote = capped_at_sentence(quote[:MAX_QUOTE_CHARS])
    note = rule_note(rule_of(text="Zebra " * 70, quote=quote))

    assert note.endswith(f'"{quote}".') and "Zebra" not in note


def test_cap_cuts_only_at_a_sentence_end_and_refuses_a_single_long_sentence():
    sentence = "Copy nothing in generators. "
    long_text = sentence * 15

    cut = capped_at_sentence(long_text.strip())

    assert cut is not None and len(cut) <= MAX_QUOTE_CHARS and cut.endswith("generators.")
    assert capped_at_sentence("word " * 80) is None
    assert capped_at_sentence("Short.") == "Short."
    assert capped_at_sentence("x" * MAX_QUOTE_CHARS) == "x" * MAX_QUOTE_CHARS


def test_pull_number_reads_github_pull_addresses_only():
    assert pull_number(URL) == 7396 and pull_number(URL + "#issuecomment-1") == 7396
    assert pull_number("https://github.com/acme/shop/issues/12") is None and pull_number("") is None


def test_the_house_rules_note_carries_the_quote_and_whole_rules_still_drop_at_the_cap():
    quoted = rule_of()
    plain = rules_of([], {}, [AuthoredLesson("w-2", "Use cents.", LessonKind.CORRECTION)])[0]

    note = standing_sentence(standing_corrections([plain, quoted], frozenset()))

    assert note.startswith(LEAD) and "Use cents." in note
    assert f'A maintainer said on PR #7396: "{QUOTE}" ({LESSON.rstrip(".")}).' in note
    assert len(note) <= MAX_NOTE_CHARS


def test_a_house_rule_whose_quote_cannot_fit_is_dropped_whole_never_cut():
    filler = AuthoredLesson("w-2", "Use cents. " * 40, LessonKind.CORRECTION)
    rules = rules_of([], {}, [filler, _item_quote()])

    note = standing_sentence(standing_corrections(rules, frozenset()))

    assert "said on PR" not in note and len(note) <= MAX_NOTE_CHARS


def _item_quote():
    return AuthoredLesson(
        "w-1", LESSON, LessonKind.RULE, source_url=URL, quote=QUOTE, quote_role="maintainer"
    )


def test_the_file_trigger_note_carries_the_quote_too():
    (match,) = file_scoped_rules(["/work/shop/src/ledger/gen.py"], [rule_of()])

    assert rule_note(match.rule).startswith(
        "[symbiont] In this repo, a maintainer said on PR #7396"
    )
