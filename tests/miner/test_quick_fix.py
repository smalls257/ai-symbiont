"""Whether the agent's first step after a failure fixed it, read from the session's records."""

from record_builders import edit, run, session, view
from symbiont.miner.quick_fix import fixed_right_away

LOCK = "fatal: Unable to create '.git/index.lock': File exists."


def _first_fixed(*after):
    records = session(run("git add a.ts", 128, LOCK), *after)
    return fixed_right_away(records[0], records)


def test_one_setup_step_then_a_pass_is_right_away():
    assert _first_fixed(run("rm -f .git/index.lock", 0, ""), run("git add a.ts", 0, ""))


def test_a_fix_chained_into_the_passing_run_is_right_away():
    assert _first_fixed(run("rm -f .git/index.lock && git add a.ts", 0, ""))


def test_a_first_step_counts_when_the_retry_then_broke_another_way():
    assert _first_fixed(
        run("rm -f .git/index.lock", 0, ""),
        run("git add a.ts", 128, "fatal: pathspec 'a.ts' did not match any files"),
        run("git add src/a.ts", 0, ""),
    )


def test_a_first_step_that_did_not_take_is_not_right_away():
    assert not _first_fixed(
        run("rm -f other.lock", 0, ""),
        run("git add a.ts", 128, LOCK),
        run("rm -f .git/index.lock", 0, ""),
        run("git add a.ts", 0, ""),
    )


def test_two_setup_steps_before_the_pass_are_not_right_away():
    assert not _first_fixed(
        run("rm -f .git/index.lock", 0, ""), run("git gc", 0, ""), run("git add a.ts", 0, "")
    )


def test_a_look_around_or_a_failed_step_fixed_nothing():
    assert not _first_fixed(view("README.md"), run("git add a.ts", 0, ""))
    assert not _first_fixed(run("pip install shop", 1, "ERROR"), run("git add a.ts", 0, ""))


def test_no_later_pass_is_not_right_away():
    assert not _first_fixed(run("rm -f .git/index.lock", 0, ""), edit("a.ts"))
