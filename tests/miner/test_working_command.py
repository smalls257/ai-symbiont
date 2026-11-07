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


def test_a_command_below_a_cd_line_is_the_working_command():
    home = "/".join(["", "Users", "pat", "Code", "repo"])
    assert working_command(f"cd {home}\npnpm api:generate") == "pnpm api:generate"
    assert working_command(f"cd {home}; pnpm test") == "pnpm test"
    assert working_command(f"cd {home} && git push && git commit -m 'x'") == "git commit -m …"


def test_redirections_and_trailing_filter_pipes_are_not_shown():
    assert working_command("pnpm api:generate 2>&1") == "pnpm api:generate"
    assert working_command("pnpm api:generate 2>&1 | head -5") == "pnpm api:generate"
    assert working_command("make >/dev/null 2>&1") == "make"
    assert working_command("make > build.log") == "make"
    assert working_command("ls src | sort | uniq -c | tail -3") == "ls src"
    assert working_command("echo a | python tool.py") == "echo a | python tool.py"


def test_a_home_path_in_a_command_is_cut_to_the_repo_relative_part():
    lock = "/".join(["", "Users", "pat", "Code", "cipher-box", ".git", "index.lock"])
    assert working_command(f"rm {lock}", frozenset({"cipher-box"})) == "rm .git/index.lock"
    assert working_command(f"rm {lock}") == "rm index.lock"
    assert "pat" not in working_command(f"cd {lock}")
