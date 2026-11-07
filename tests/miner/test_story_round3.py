"""Story fix round 3: a read-only step is never the setup; shown commands start at the program."""

from record_builders import run, session
from symbiont.miner.environment_fix import setup_command
from symbiont.miner.read_only import changing_command, is_read_only
from symbiont.miner.working_command import working_command

LOOK = "git log --oneline -1"


def test_the_look_around_commands_are_read_only():
    assert is_read_only(LOOK) and is_read_only(f"{LOOK} && git status")
    assert changing_command(LOOK) == "" and changing_command(f"{LOOK} && git status") == ""


def test_a_chain_that_changes_things_is_named_by_the_step_that_changed_them():
    assert changing_command(f"git commit -m x && {LOOK}") == "git commit -m x"
    assert changing_command(f"cd /repo && npm install && {LOOK}") == "npm install"


def test_the_setup_is_not_the_read_only_tail_of_a_chain():
    failed = run("pnpm test", 1, "boom")
    steps = session(failed, run(f"git commit -m x && {LOOK}"), run("pnpm test", 0, "ok"))
    assert setup_command(steps[0], steps) == "git commit -m x"
    only_looking = session(failed, run(LOOK), run(f"{LOOK} && git status"), run("pnpm test", 0))
    assert setup_command(only_looking[0], only_looking) is None


def test_shown_commands_start_at_the_program():
    gateway = "RECOVERY_GATEWAY=http://gateway.example:8080"
    command = f'{gateway} SDK_MODE="a b" pnpm exec playwright test e2e'
    assert working_command(command) == "pnpm exec playwright test e2e"
    assert working_command("env -i FOO=1 make build") == "make build"
    assert working_command("cd /repo && X=1 make 2>&1") == "make"
