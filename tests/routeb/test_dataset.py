"""Route B training data: examples built only from what the history shows.

All fixtures are hand-written; no network, no clock. The failure these tests
guard against is a Silent Fallback: inventing a correction target when the
history holds none, or training on a held-out task.
"""

from dataclasses import replace

from record_builders import edit, replace_text, review, run, say, session, user
from symbiont.miner.mine import mine_chain
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.signals.correction import find_corrections
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.miner.signals.reworked_edit import find_reworked_edits
from symbiont.routeb.dataset import (
    DatasetLimits,
    build_dataset,
    correction_pairs,
    recall_pairs,
)
from symbiont.routeb.signal_texts import CORRECTION_BY_SIGNAL, RECALL_BY_SIGNAL

DIALECT = "sqlglot/dialects/dialect.py"
DUCKDB = "sqlglot/dialects/duckdb.py"
TEST_DUCKDB = "tests/dialects/test_duckdb.py"
REFERENCES = {DIALECT: frozenset({DUCKDB}), DUCKDB: frozenset({TEST_DUCKDB})}
IMPORT_ERROR = (
    "tests/dialects/test_duckdb.py:3: in <module>\n"
    "E   ImportError: cannot import name 'ArraySort' from 'sqlglot.expressions'\n"
    "ERROR tests/dialects/test_duckdb.py\n1 error in 0.31s"
)
FAILED = "FAILED tests/dialects/test_duckdb.py::TestDuckDB::test_cast - AssertionError\n1 failed"


def failed_then_fixed():
    return session(
        user("Make the duckdb tests pass"),
        run("pytest tests/dialects/test_duckdb.py -q", 1, IMPORT_ERROR),
        run("pytest tests/dialects/test_duckdb.py -q -x", 1, IMPORT_ERROR),
        run(
            "python -m pytest tests/dialects/test_duckdb.py -q --import-mode=importlib",
            0,
            "12 passed",
        ),
    )


def test_corrected_command_is_the_one_that_succeeded():
    s = failed_then_fixed()
    (pain,) = find_failed_commands(s)[:1]
    got = correction_pairs(pain, s)
    assert got.reason is None
    (example,) = got.examples
    assert (
        example.completion
        == "python -m pytest tests/dialects/test_duckdb.py -q --import-mode=importlib"
    )
    assert example.sources == (("s1", 1), ("s1", 3))
    assert "ImportError: cannot import name 'ArraySort'" in example.prompt


def test_surviving_edit_is_last_version():
    s = session(
        replace_text(DIALECT, "x = 1", "x = 2"),
        replace_text(DIALECT, "x = 2", "x = 3"),
        replace_text(DIALECT, "x = 3", "x = 4"),
    )
    first_rework = find_reworked_edits(s)[0]
    (example,) = correction_pairs(first_rework, s).examples
    assert "+x = 4" in example.completion
    assert "+x = 3" not in example.completion
    assert example.sources[-1] == ("s1", 2)


def test_edit_pair_shows_the_discarded_version_as_the_situation():
    s = session(replace_text(DIALECT, "x = 1", "x = 2"), replace_text(DIALECT, "x = 2", "x = 3"))
    (example,) = correction_pairs(find_reworked_edits(s)[0], s).examples
    assert "+x = 2" in example.prompt
    assert DIALECT in example.prompt


def test_correction_target_is_the_step_after_the_user_correction():
    s = session(
        user("Fix TRY_CAST for duckdb"),
        edit(DIALECT, diff="-a\n+change the base\n"),
        run("pytest tests/dialects/test_duckdb.py", 1, FAILED),
        user("You broke duckdb, revert dialect.py and do it in the subclass"),
        edit(DUCKDB, diff="-a\n+override in the subclass\n"),
    )
    (pain,) = find_corrections(s)
    (example,) = correction_pairs(pain, s).examples
    assert "+override in the subclass" in example.completion
    assert "You broke duckdb, revert dialect.py and do it in the subclass" in example.prompt
    assert example.sources == (("s1", 2), ("s1", 3), ("s1", 4))


def test_blast_radius_teaches_the_files_that_should_have_been_read():
    s = session(edit(DIALECT), run("pytest tests/dialects/test_duckdb.py", 1, FAILED))
    (pain,) = [p for p in mine_chain([s], REFERENCES) if p.signature.signal == Signal.BLAST_RADIUS]
    (example,) = correction_pairs(pain, s).examples
    assert DUCKDB in example.completion
    assert DIALECT in example.prompt
    assert "AssertionError" in example.prompt


def test_hub_breakage_is_not_a_correction_source():
    s = session(edit(DIALECT), run("pytest tests/dialects/test_duckdb.py", 1, FAILED))
    (pain,) = [p for p in mine_chain([s], REFERENCES) if p.signature.signal == Signal.BLAST_RADIUS]
    got = correction_pairs(pain, s, hubs=frozenset({DUCKDB}))
    assert got.examples == ()
    assert "hub" in got.reason


def test_rework_of_a_scratch_file_is_not_a_correction_source():
    created = edit("scratch.py", diff="--- /dev/null\n+++ b/scratch.py\n@@ -0,0 +1 @@\n+x = 1\n")
    s = session(created, replace_text("scratch.py", "x = 1", "x = 2"))
    (pain,) = find_reworked_edits(s)
    got = correction_pairs(pain, s)
    assert got.examples == ()
    assert "scratch" in got.reason
    assert recall_pairs(pain, s).examples == ()


def test_review_flag_target_is_the_edit_that_answered_it():
    s = session(
        edit(DIALECT, diff="+return None\n"),
        review(DIALECT, "+return None\n", "This swallows the error"),
        edit(DIALECT, diff="-return None\n+raise ValueError\n"),
    )
    pain = PainPoint(Signature(Signal.REVIEW_FLAG, (DIALECT,)), "s1", 1, (("s1", 1), ("s1", 2)))
    (example,) = correction_pairs(pain, s).examples
    assert "+raise ValueError" in example.completion
    assert "This swallows the error" in example.prompt


def test_no_pairs_without_a_correction_source():
    never_fixed = session(
        user("go"), run("pytest tests/dialects/test_duckdb.py -q", 1, IMPORT_ERROR)
    )
    (pain,) = find_failed_commands(never_fixed)
    got = correction_pairs(pain, never_fixed)
    assert got.examples == ()
    assert got.reason
    assert "no later command" in got.reason


def test_correction_with_no_action_after_it_has_no_pairs():
    s = session(
        user("Fix it"),
        edit(DIALECT),
        run("pytest tests/dialects/test_duckdb.py", 1, FAILED),
        user("You broke dialect.py", tags=("correction",)),
    )
    (pain,) = find_corrections(s)
    got = correction_pairs(pain, s)
    assert got.examples == ()
    assert got.reason


def test_a_loop_has_no_correction_source():
    pain = PainPoint(
        Signature(Signal.LOOP, ("command", "ls")), "s1", 2, (("s1", 0), ("s1", 1), ("s1", 2))
    )
    got = correction_pairs(pain, session(run("ls"), run("ls"), run("ls")))
    assert got.examples == ()
    assert "loop" in got.reason


def test_a_citation_missing_from_the_records_is_reported_not_guessed():
    pain = PainPoint(
        Signature(Signal.FAILED_COMMAND, ("pytest", "x.py", "exit 1")), "gone", 4, (("gone", 4),)
    )
    for pairs in (recall_pairs, correction_pairs):
        got = pairs(pain, failed_then_fixed())
        assert got.examples == ()
        assert "gone" in got.reason


def test_recall_quotes_original_text_not_a_summary():
    s = failed_then_fixed()
    (pain,) = find_failed_commands(s)[:1]
    (example,) = recall_pairs(pain, s).examples
    assert example.prompt.startswith("What broke last time I ran")
    assert "pytest tests/dialects/test_duckdb.py -q" in example.prompt
    assert IMPORT_ERROR in example.completion


def test_recall_of_a_correction_quotes_the_users_words():
    s = session(
        user("Fix it"),
        edit(DIALECT),
        run("pytest tests/dialects/test_duckdb.py", 1, FAILED),
        user("You broke duckdb, revert dialect.py and do it in the subclass"),
    )
    (pain,) = find_corrections(s)
    (example,) = recall_pairs(pain, s).examples
    assert "You broke duckdb, revert dialect.py and do it in the subclass" in example.completion
    assert DIALECT in example.prompt


def test_long_output_is_quoted_from_its_end_verbatim():
    long_output = "noise line\n" * 500 + "E   ImportError: cannot import name 'ArraySort'\n"
    s = session(
        run("pytest tests/dialects/test_duckdb.py -q", 1, long_output),
        run("pytest tests/dialects/test_duckdb.py", 0, "ok"),
    )
    (pain,) = find_failed_commands(s)
    (example,) = recall_pairs(pain, s, max_quote_chars=200).examples
    assert example.completion.endswith("ImportError: cannot import name 'ArraySort'\n")
    assert long_output[-150:] in example.completion
    assert len(example.completion) < 500


def test_examples_carry_whether_every_source_is_spark_safe():
    s = failed_then_fixed()
    private = [
        replace(r, provenance=replace(r.provenance, spark_safe=False)) if r.step == 3 else r
        for r in s
    ]
    (pain,) = find_failed_commands(s)[:1]
    assert recall_pairs(pain, s).examples[0].spark_safe is True
    assert correction_pairs(pain, private).examples[0].spark_safe is False


# --- selection and hold-out ---------------------------------------------------


def repeated_trouble(session_id: str, command: str, times: int):
    records = []
    for _ in range(times):
        records += [run(command, 1, IMPORT_ERROR), run(command + " --fixed", 0, "ok")]
    return [replace(r, session_id=session_id, step=i) for i, r in enumerate(session(*records))]


def test_top_n_keeps_the_most_recurrent_troubles_only():
    records = (
        repeated_trouble("a", "pytest tests/test_a.py", 3)
        + repeated_trouble("b", "pytest tests/test_b.py", 2)
        + repeated_trouble("c", "pytest tests/test_c.py", 1)
    )
    pains = [
        p
        for sid in "abc"
        for p in find_failed_commands([r for r in records if r.session_id == sid])
    ]
    built = build_dataset(pains, records, DatasetLimits(2, frozenset()))
    kept = {p.signature.key[1] for p in built.pain_points}
    assert kept == {"tests/test_a.py", "tests/test_b.py"}
    assert built.dropped["beyond top-N"] == 1


def test_top_n_is_a_parameter_not_a_constant():
    records = repeated_trouble("a", "pytest tests/test_a.py", 1) + repeated_trouble(
        "b", "pytest tests/test_b.py", 1
    )
    pains = [
        p for sid in "ab" for p in find_failed_commands([r for r in records if r.session_id == sid])
    ]
    assert len(build_dataset(pains, records, DatasetLimits(1, frozenset())).pain_points) == 1
    assert len(build_dataset(pains, records, DatasetLimits(5, frozenset())).pain_points) == 2


def test_holdout_tasks_never_in_examples():
    kept = repeated_trouble("keep", "pytest tests/test_a.py", 2)
    held = [
        replace(r, task_id="tobymao__sqlglot-1234")
        for r in repeated_trouble("held", "pytest tests/test_a.py", 2)
    ]
    records = kept + held
    pains = find_failed_commands(kept) + find_failed_commands(held)
    built = build_dataset(pains, records, DatasetLimits(10, frozenset({"tobymao/sqlglot#1234"})))
    assert built.examples
    assert all(ref[0] == "keep" for e in built.examples for ref in e.sources)
    assert built.dropped["held-out task"] == len(find_failed_commands(held))


def test_a_held_out_session_is_not_used_as_a_correction_target_either():
    broke = [
        replace(r, session_id="mine")
        for r in session(run("pytest tests/test_a.py", 1, IMPORT_ERROR))
    ]
    held_fix = [
        replace(r, session_id="held", task_id="tobymao/sqlglot#1234")
        for r in session(run("pytest tests/test_a.py -q", 0, "ok"))
    ]
    built = build_dataset(
        find_failed_commands(broke),
        broke + held_fix,
        DatasetLimits(10, frozenset({"tobymao__sqlglot-1234"})),
    )
    assert [e for e in built.examples if e.kind == "correction"] == []


def test_unrecognised_task_id_is_refused_when_something_is_held_out():
    import pytest

    from symbiont.records.holdout import UnrecognisedTaskIdError

    records = [replace(r, task_id="my own task") for r in failed_then_fixed()]
    with pytest.raises(UnrecognisedTaskIdError):
        build_dataset([], records, DatasetLimits(1, frozenset({"tobymao/sqlglot#1"})))


def test_dataset_reports_why_a_pain_point_gave_no_examples():
    s = session(run("pytest tests/dialects/test_duckdb.py -q", 1, IMPORT_ERROR), say("hm"))
    built = build_dataset(find_failed_commands(s), s, DatasetLimits(3, frozenset()))
    assert len(built.examples) == 1  # the recall pair still stands
    assert any("no later command" in why for why in built.skipped)


def test_every_signal_has_a_recall_and_a_correction_wording():
    assert set(RECALL_BY_SIGNAL) == set(Signal)
    assert set(CORRECTION_BY_SIGNAL) == set(Signal)
