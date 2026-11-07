from record_builders import run, say, session
from symbiont.miner.failure_keys import broke_in_words, what_broke
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.miner.tool_messages import tool_message

GIT_FATAL = (
    "Exit code 128\nwarning: could not open directory 'a/b/'\n"
    "fatal: pathspec 'a/b/c.ts' did not match any files"
)
PATHSPEC = "fatal: pathspec <x> did not match any files"


def test_a_printed_complaint_is_what_broke():
    assert what_broke(run("git add a.py", 128, GIT_FATAL), "git add", inline=False) == PATHSPEC


def test_shell_exit_codes_have_meanings():
    assert what_broke(run("make", 143, ""), "make", inline=False) == "stopped by a timeout"
    assert what_broke(run("nope", 127, ""), "nope", inline=False) == "command not found"


def test_error_class_still_wins():
    raw = "ValueError: bad\nfatal: pathspec 'x' did not match any files"
    assert what_broke(run("tool", 1, raw), "tool", inline=False) == "ValueError"


def test_placeholders_read_as_prose():
    assert broke_in_words(PATHSPEC) == "pathspec … did not match any files"
    assert broke_in_words("HTTP 401: Bad credentials (<url>)") == "HTTP 401: Bad credentials (…)"
    assert broke_in_words("Expected <n> got <n>") == "Expected N got N"


def test_a_failed_command_is_keyed_by_subcommand_and_complaint():
    s = session(say("add it"), run("git add a.py", 128, GIT_FATAL))
    assert [p.signature.key for p in find_failed_commands(s)] == [("git add", "a.py", PATHSPEC)]


def test_a_cut_inside_a_placeholder_leaves_no_fragment():
    long_line = "error: " + "x" * 105 + " see https://example.test/a/b"
    message = tool_message(long_line)
    assert message is not None and "<" not in message
    assert "<" not in broke_in_words(message)
    broke = what_broke(run("tool", 1, long_line), "tool", inline=False)
    assert "<" not in broke_in_words(broke)


def test_a_signature_cut_inside_a_placeholder_leaves_no_fragment():
    raw = "E   assert " + "y" * 45 + " in /a/b/c.py"
    broke = what_broke(run("pytest", 1, raw), "pytest", inline=False)
    assert broke.startswith("assert yyy") and "<" not in broke_in_words(broke)


def test_error_and_hint_labels_are_dropped():
    assert broke_in_words("error: no such thing") == "no such thing"
    assert broke_in_words("hint: try again") == "try again"


def test_no_credential_reaches_a_message_or_a_key():
    password = "ghp_" + "a" * 36
    bearer = "t0k3n" + "Z" * 24
    cases = (
        (password, f"fatal: Authentication failed for 'https://user:{password}@github.com/o/r'"),
        (bearer, f"Error: request rejected, Authorization: Bearer {bearer}"),
    )
    for secret, output in cases:
        assert tool_message(output) and secret not in tool_message(output)
        broke = what_broke(run("git push", 1, output), "git", inline=False)
        assert secret not in broke
