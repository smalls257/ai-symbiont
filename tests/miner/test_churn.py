"""Churn: edits per file per session, for the dashboard; never a lesson."""

from dataclasses import replace

from record_builders import edit, run, session
from symbiont.miner.churn import FileChurn, churn
from symbiont.miner.mine import mine_chain
from symbiont.miner.painpoint import Signal

REPO = frozenset({"sqlglot"})


def test_churn_counts_edits_per_file_per_session_repo_relative():
    first = session(
        edit("/work/sqlglot/sqlglot/parser.py"),
        edit("sqlglot/parser.py"),
        edit("./tests/test_parser.py"),
    )
    second = [replace(r, session_id="s2") for r in session(edit("sqlglot/parser.py"))]
    assert churn([first, second], REPO) == [
        FileChurn("sqlglot/parser.py", "s1", 2),
        FileChurn("tests/test_parser.py", "s1", 1),
        FileChurn("sqlglot/parser.py", "s2", 1),
    ]


def test_churn_skips_files_outside_the_repo_and_scratch_files_deleted_in_session():
    steps = session(
        edit("/home/me/.config/tool.toml"),
        edit("/tmp/probe.py"),
        edit("../other/file.py"),
        edit("scratch_repro.py"),
        edit("scratch_repro.py"),
        run("rm scratch_repro.py"),
        edit("kept_script.py"),
        edit("sqlglot/parser.py", exit_code=1),
    )
    assert churn([steps], REPO) == [FileChurn("kept_script.py", "s1", 1)]


def test_rework_no_longer_produces_lessons():
    from record_builders import replace_text

    steps = session(
        replace_text("sqlglot/parser.py", "x = 1", "x = compute_offset(node)"),
        replace_text("sqlglot/parser.py", "x = compute_offset(node)", "x = 2"),
    )
    assert [p for p in mine_chain([steps], {}) if p.signature.signal is Signal.REWORKED_EDIT] == []
    assert churn([steps], REPO) == [FileChurn("sqlglot/parser.py", "s1", 2)]
