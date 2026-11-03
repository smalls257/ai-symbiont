"""A check is unfinished when its latest run failed and no later same-check run passed."""

from record_builders import edit, run, session
from symbiont.miner.unfinished_check import unfinished_check

RED = "E   - a\nE   + b\n1 failed in 0.1s"


def test_red_last_is_unfinished_with_the_diff():
    found = unfinished_check(session(run("uv run pytest tests/a.py -q", 1, RED)))
    assert found.check == "pytest tests/a.py" and "- a / + b" in found.excerpt


def test_red_then_green_is_finished():
    assert (
        unfinished_check(
            session(
                run("pytest tests/a.py", 1, RED),
                edit("a.py"),
                run("pytest tests/a.py", 0, "1 passed"),
            )
        )
        is None
    )


def test_a_broader_green_run_closes_it_but_a_disjoint_one_does_not():
    red = run("pytest tests/a.py", 1, RED)
    assert unfinished_check(session(red, run("pytest", 0, "9 passed"))) is None
    assert unfinished_check(session(red, run("pytest tests/b.py", 0, "1 passed"))) is not None


def test_unrelated_commands_never_count():
    assert (
        unfinished_check(session(run("ls nothing", 2, "ls: nothing"), run("grep x f", 1, "")))
        is None
    )


def test_a_later_green_of_another_tool_does_not_clear_it():
    assert (
        unfinished_check(session(run("pytest tests/a.py", 1, RED), run("ruff check .", 0)))
        is not None
    )
