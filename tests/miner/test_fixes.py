"""Which resolutions count as a known fix: a codebase edit or a corrected command, nothing else."""

from record_builders import edit, run, session
from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import lessons_from
from symbiont.miner.signals.failed_command import find_failed_commands

TEST = "pytest tests/test_parser.py -q"


def fix_of(*records):
    records = session(*records)
    (lesson,) = lessons_from(find_failed_commands(records), records)
    return lesson.fix


def test_an_edit_inside_the_codebase_is_a_code_fix():
    parser = "sqlglot/parser.py:12\nE   NameError: name 'Token' is not defined"
    assert fix_of(run(TEST, 1, parser), edit("sqlglot/parser.py"), run(TEST, 0, "ok")) is (
        FixKind.CODE_FIX
    )


def test_an_edit_to_a_scratch_file_is_not_a_fix():
    parser = "sqlglot/parser.py:1\nE   NameError: name 'x'"
    scratch = edit("/tmp/repro_parser.py")
    assert fix_of(run(TEST, 1, parser), scratch, run(TEST, 0, "ok")) is None


def test_a_corrected_command_is_a_fix_but_a_respelled_pass_is_not():
    corrected = fix_of(run("pytest tests/a.py", 5, "no tests ran"), run("pytest tests/x/a.py", 0))
    assert corrected is FixKind.CORRECTED_COMMAND
    assert fix_of(run(TEST, 1, "E   assert 1 == 2"), run(f"{TEST} -x", 0)) is None
