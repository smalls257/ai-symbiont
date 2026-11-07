from record_builders import run, say, session
from symbiont.miner.failure_keys import broke_in_words, what_broke
from symbiont.miner.signals.failed_command import find_failed_commands

GIT_FATAL = (
    "Exit code 128\nwarning: could not open directory 'a/b/'\n"
    "fatal: pathspec 'a/b/c.ts' did not match any files"
)
PATHSPEC = "fatal: pathspec <x> did not match any files"


def _record(command: str, code: int, raw: str):
    return run(command, code, raw)


def test_a_printed_complaint_is_what_broke():
    assert what_broke(_record("git add a.py", 128, GIT_FATAL), "git add", inline=False) == PATHSPEC


def test_shell_exit_codes_have_meanings():
    assert what_broke(_record("make", 143, ""), "make", inline=False) == "stopped by a timeout"
    assert what_broke(_record("nope", 127, ""), "nope", inline=False) == "command not found"


def test_error_class_still_wins():
    raw = "ValueError: bad\nfatal: pathspec 'x' did not match any files"
    assert what_broke(_record("tool", 1, raw), "tool", inline=False) == "ValueError"


def test_placeholders_read_as_prose():
    assert broke_in_words(PATHSPEC) == "pathspec … did not match any files"
    assert broke_in_words("HTTP 401: Bad credentials (<url>)") == "HTTP 401: Bad credentials (…)"
    assert broke_in_words("Expected <n> got <n>") == "Expected N got N"


def test_a_failed_command_is_keyed_by_subcommand_and_complaint():
    s = session(say("add it"), run("git add a.py", 128, GIT_FATAL))
    assert [p.signature.key for p in find_failed_commands(s)] == [("git add", "a.py", PATHSPEC)]
