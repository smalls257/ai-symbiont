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


def created(path):
    return edit(path, diff=f"--- /dev/null\n+++ b/{path}\n+x\n")


def test_churn_skips_files_outside_the_repo_and_scratch_files_deleted_in_session():
    steps = session(
        edit("/home/me/.config/tool.toml"),
        edit("/tmp/probe.py"),
        edit("/elsewhere/other/file.py"),
        edit("../other/file.py"),
        created("pkg/scratch_repro.py"),
        edit("pkg/scratch_repro.py"),
        run("rm pkg/scratch_repro.py"),
        edit("pkg/kept.py"),
        edit("sqlglot/parser.py", exit_code=1),
    )
    assert churn([steps], REPO) == [FileChurn("pkg/kept.py", "s1", 1)]


def test_only_a_file_created_in_the_session_and_then_removed_is_scratch():
    steps = session(
        edit("pkg/x.py"),  # existed before the session: removing it later does not erase the edit
        run("rm pkg/x.py"),
        edit("top/x.py"),
        created("pkg/y.py"),
        run("rm other/y.py"),  # a different file with the same base name
    )
    assert churn([steps], REPO) == [
        FileChurn("pkg/x.py", "s1", 1),
        FileChurn("pkg/y.py", "s1", 1),
        FileChurn("top/x.py", "s1", 1),
    ]


def test_an_absolute_path_counts_only_below_a_repo_directory():
    inside = session(edit("/work/sqlglot/sqlglot/parser.py"))
    outside = [replace(r, session_id="s2") for r in session(edit("/work/other/sqlglot_like.py"))]
    assert churn([inside, outside], REPO) == [FileChurn("sqlglot/parser.py", "s1", 1)]


def test_rework_no_longer_produces_lessons():
    from record_builders import replace_text

    steps = session(
        replace_text("sqlglot/parser.py", "x = 1", "x = compute_offset(node)"),
        replace_text("sqlglot/parser.py", "x = compute_offset(node)", "x = 2"),
    )
    assert [p for p in mine_chain([steps], {}) if p.signature.signal is Signal.REWORKED_EDIT] == []
    assert churn([steps], REPO) == [FileChurn("sqlglot/parser.py", "s1", 2)]
