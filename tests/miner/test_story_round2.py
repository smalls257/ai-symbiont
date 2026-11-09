"""Story fix round 2: pipes that end early, home paths on every branch, retries, command text."""

from dataclasses import replace

from record_builders import edit, run, session
from story_builders import owners_lesson
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_chain, sessions_of
from symbiont.miner.story import PASSED_AGAIN, story_of
from symbiont.miner.working_command import working_command

HOME = "/".join(["", "Users", "pat", "Code", "repo"])
LOCK = f"{HOME}/.git/index.lock"
REPOS = frozenset({"repo"})


def lesson_of(records):
    return lessons_from(mine_chain(sessions_of(records), {}), records, frozenset())[0]


def test_a_dangling_or_empty_pipe_never_breaks_the_command_line():
    assert working_command("ls |") == "ls"
    assert working_command("|") == ""
    assert working_command("ls | | sort") == "ls"
    assert working_command("echo hi ||") == "echo hi"


def test_a_greater_than_inside_quotes_is_not_a_redirection():
    assert working_command('python -c "print(1 > 2)"') == 'python -c "print(1 > 2)"'
    assert working_command('python -c "print(1 > 2)" > out.txt') == 'python -c "print(1 > 2)"'


def test_home_paths_are_cut_on_both_error_branches():
    typescript = f"{HOME}/src/a.ts(3,1): error TS2307: Cannot find module '{HOME}/x'."
    plain = f"Error: cannot open '{LOCK}'"
    for error in (typescript, plain):
        lesson = replace(owners_lesson(), error_lines=(error,), complaint="", quote="$ x\n")
        broke = story_of(lesson, repo_names=REPOS).broke
        assert "/Users" not in broke and "pat" not in broke, broke
    shown = story_of(replace(owners_lesson(), error_lines=(typescript,), complaint=""), "", REPOS)
    assert "a.ts:3" in shown.broke and "TS2307" in shown.broke


def test_a_fix_that_is_only_the_rerun_reads_as_passing_when_run_again():
    lesson = replace(
        owners_lesson(), resolution=("re-ran pnpm",), fix_commands=("pnpm api:generate",)
    )
    lesson = replace(lesson, pain_point=lesson.pain_point, fix=None)
    ended = story_of(lesson).ended
    assert ended == PASSED_AGAIN or "passed when run again" in ended
    assert "fixed by running" not in ended


COMMIT = (
    "git commit -m \"$(cat <<'EOF'\n"
    "Add the mounting layer\n\n1. Writes a file via the FUSE mount and then reads it back\n"
    'EOF\n)"'
)


def test_a_heredoc_command_never_leaks_its_message_as_the_error():
    fatal = "fatal: failed to write commit object"
    out = f"error: unable to write loose object\n{fatal}"
    lesson = lesson_of(session(run(COMMIT, 128, out), run("rm x"), run(COMMIT, 0, "ok")))
    for old in (lesson, replace(lesson, failed_command="", complaint="")):
        broke = story_of(old).broke
        assert "FUSE" not in broke and "EOF" not in broke
    assert story_of(lesson).broke.endswith("failed to write commit object")


def test_a_clipped_heredoc_head_with_no_output_says_the_exit_not_the_message():
    quote = "$ " + COMMIT.split("EOF\n)")[0][:150] + "[...]"
    lesson = replace(owners_lesson(), error_lines=(), complaint="", failed_command="", quote=quote)
    pain = replace(
        lesson.pain_point,
        signature=replace(lesson.pain_point.signature, key=("git commit", "-", "exit 128")),
    )
    broke = story_of(replace(lesson, pain_point=pain)).broke
    assert broke.endswith("failed (exit 128)") and "FUSE" not in broke


def test_the_complaint_beats_git_s_trailing_hints():
    out = (
        f"fatal: Unable to create '{LOCK}': File exists.\n\n"
        "Another git process seems to be running in this repository, e.g.\n"
        "hint: See the manual\n"
        "If no other git process is currently running, this probably means a git process crashed\n"
        "remove the file manually to continue.\n"
    )
    lesson = lesson_of(session(run("git pull", 128, out), edit("a.py"), run("git pull", 0, "")))
    broke = story_of(lesson, repo_names=REPOS).broke
    assert broke.endswith("Unable to create '.git/index.lock': File exists.")


def test_in_an_and_chain_the_example_is_the_first_working_step():
    assert (
        working_command("git add pnpm-lock.yaml && git commit -m 'x'") == "git add pnpm-lock.yaml"
    )
    assert working_command(f"cd {HOME} && make build && make test") == "make build"
    assert working_command("make build; make test") == "make test"
    assert working_command("a || b") == "a"
