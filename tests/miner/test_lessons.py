"""Lessons carry their own quote, resolution and privacy flag, so no record needs keeping.

Hand-written records only.
"""

from dataclasses import replace

import pytest

from record_builders import edit, run, session, user
from symbiont.miner.lessons import (
    QUOTE_CHARS,
    Coverage,
    excerpt,
    lessons_from,
    resolution_coverage,
)
from symbiont.miner.mine import mine_chain, mine_history, sessions_of
from symbiont.miner.painpoint import Signal
from symbiont.records.schema import Provenance, Record

PRIVATE = Provenance(dataset="SWE-chat", license="ODC-BY", spark_safe=False)
TEST = "pytest tests/test_parser.py -q"
BROKE = "E   ModuleNotFoundError: No module named 'yaml'\n1 error"


def fixed_by_install():
    return session(
        user("make the parser tests pass"),
        run(TEST, 1, BROKE),
        run("pip install pyyaml"),
        run(TEST, 0, "3 passed"),
    )


def never_fixed():
    return [replace(r, session_id="s2") for r in session(run(TEST, 1, BROKE))]


def lessons_of(records):
    return lessons_from(mine_chain(sessions_of(records), {}), records)


def test_a_lesson_quotes_what_happened_and_names_what_fixed_it():
    (lesson,) = lessons_of(fixed_by_install())
    assert lesson.quote.startswith(f"$ {TEST}\n") and "No module named 'yaml'" in lesson.quote
    assert lesson.resolution == ("ran `pip install pyyaml`", f"ran `{TEST}`")
    assert lesson.unresolved_because is None
    assert lesson.sources == (("s1", 1), ("s1", 2), ("s1", 3))
    assert lesson.spark_safe


def test_an_unresolved_lesson_says_why():
    (lesson,) = lessons_of(never_fixed())
    assert lesson.resolution == ()
    assert "no later command" in (lesson.unresolved_because or "")


def test_the_quote_is_bounded_and_keeps_the_end_of_command_output():
    long_output = "noise\n" * 500 + "E   ImportError: cannot import name 'Foo'"
    (lesson,) = lessons_of(session(run(TEST, 1, long_output)))
    assert len(lesson.quote) <= QUOTE_CHARS
    assert lesson.quote.endswith("cannot import name 'Foo'")


def test_excerpt_of_prose_keeps_the_start_within_the_limit():
    text = excerpt(user("please stop " * 100), 50)
    assert len(text) <= 50 and text.startswith("please stop")


def test_the_privacy_flag_is_false_when_any_record_used_is_private():
    records = fixed_by_install()
    records[2] = replace(records[2], provenance=PRIVATE)  # only the install step is private
    (lesson,) = lessons_of(records)
    assert lesson.spark_safe is False


def test_a_missing_cited_record_raises_rather_than_quoting_nothing():
    records = fixed_by_install()
    pains = mine_chain([records], {})
    with pytest.raises(LookupError, match="s1:1"):
        lessons_from(pains, [r for r in records if r.step != 1])


def test_coverage_counts_resolved_lessons_per_signal_and_lists_every_signal():
    records = fixed_by_install() + never_fixed()
    coverage = resolution_coverage(lessons_of(records))
    assert coverage[Signal.FAILED_COMMAND] == Coverage(resolved=1, total=2)
    assert coverage[Signal.LOOP] == Coverage(resolved=0, total=0)
    assert set(coverage) == set(Signal)


def test_an_edit_step_names_the_file_and_its_first_new_line():
    added = "+install_requires=['pyyaml']\n"
    failure = f"{BROKE}\nhint: check setup.py"
    records = session(run(TEST, 1, failure), edit("setup.py", diff=added), run(TEST, 0, "ok"))
    (lesson,) = lessons_of(records)
    assert lesson.resolution[0] == "edited `setup.py` to add `install_requires=['pyyaml']`"


def test_an_unrelated_edit_is_worded_as_alongside_not_as_the_fix():
    records = session(
        run(TEST, 1, BROKE),
        edit("docs/notes.md"),
        run("pip install pyyaml"),
        run(TEST, 0, "ok"),
    )
    (lesson,) = lessons_of(records)
    assert lesson.resolution == ("ran `pip install pyyaml`", f"ran `{TEST}`")
    assert lesson.changed_alongside == ("edited `docs/notes.md` to add `b`",)


def test_history_chains_timed_sessions_and_mines_untimed_ones_alone():
    monday = [replace(r, session_id="mon", ts="2026-10-26T09:00:00") for r in never_fixed()]
    tuesday = [replace(r, session_id="tue", ts="2026-10-27T09:00:00") for r in never_fixed()]
    found = mine_history(sessions_of(tuesday + monday + never_fixed()), {})
    assert [p.session_id for p in found] == ["mon", "tue", "s2"]


def test_a_lesson_with_unrelated_changes_pickles_without_any_record():
    import pickle

    records = session(run(TEST, 1, BROKE), edit("docs/changelog.md"), run(TEST, 0, "ok"))
    (lesson,) = lessons_of(records)
    assert "never names" in (lesson.unresolved_because or "")
    assert lesson.changed_alongside
    revived = pickle.loads(pickle.dumps(lesson))
    assert not any(isinstance(v, Record) for v in vars(revived).values())
    assert b"Record" not in pickle.dumps(lesson).replace(b"PainPoint", b"")
