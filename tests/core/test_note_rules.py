from record_builders import edit, run, session, user
from symbiont.core.note_rules import NOTE_BUDGET, NOTE_COOLDOWN, may_speak, step_trouble
from symbiont.miner.painpoint import Signal, Signature


def test_a_failed_command_is_a_boundary_named_by_the_miner_signature():
    prefix = session(user("fix it"), run("pytest tests/test_x.py", 1, "ImportError: no x"))
    assert step_trouble(prefix) == Signature(
        Signal.FAILED_COMMAND, ("pytest", "tests/test_x.py", "ImportError")
    )


def test_an_empty_grep_is_not_a_boundary():
    assert step_trouble(session(run("grep -r foo .", 1))) is None


def test_a_passing_command_and_a_first_edit_are_not_boundaries():
    assert step_trouble(session(run("pytest", 0))) is None
    assert step_trouble(session(edit("a.py"))) is None
    assert step_trouble([]) is None


def test_a_second_applied_edit_of_the_same_file_is_a_boundary():
    prefix = session(edit("a.py"), run("pytest", 0), edit("a.py"))
    assert step_trouble(prefix) == Signature(Signal.REWORKED_EDIT, ("a.py",))


def test_an_edit_after_a_rejected_edit_is_not_a_boundary():
    assert step_trouble(session(edit("a.py", exit_code=1), edit("a.py"))) is None


def test_budget_and_cooldown():
    assert may_speak([], 0)
    assert not may_speak([3], 3 + NOTE_COOLDOWN)
    assert may_speak([3], 3 + NOTE_COOLDOWN + 1)
    spent = [i * 10 for i in range(NOTE_BUDGET)]
    assert not may_speak(spent, 1000)
