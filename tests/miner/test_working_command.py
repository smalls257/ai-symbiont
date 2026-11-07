"""An example line is the working command on one line, never a heredoc or a message body."""

from symbiont.miner.working_command import LINE_CHARS, working_command

COMMIT = "git commit -m \"$(cat <<'EOF'\nFix the vault bug\n\nA long body.\nEOF\n)\""


def test_a_commit_with_a_heredoc_message_shows_the_command_only():
    assert working_command(COMMIT) == "git commit -m …"
    assert working_command("cd /repo && " + COMMIT) == "git commit -m …"


def test_a_quoted_commit_message_is_dropped_but_the_rest_stays():
    assert working_command("git commit -m 'fix: x' -- a.py") == "git commit -m … -- a.py"


def test_the_cd_prefix_goes_and_a_long_line_is_cut_to_one_short_line():
    assert working_command("cd app && pnpm exec vitest run") == "pnpm exec vitest run"
    long = working_command("pytest " + "tests/some/dir/test_file.py " * 10)
    assert len(long) <= LINE_CHARS and "\n" not in long
