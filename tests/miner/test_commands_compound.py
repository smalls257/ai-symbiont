import pytest

from symbiont.miner.commands import program_words, status_program
from symbiont.miner.resolutions import subcommand_of

CASES = [
    ("cd /repo\nenv -u GITHUB_TOKEN gh pr edit 476", "gh"),
    ("env -u GITHUB_TOKEN git push", "git"),
    ("env -i PATH=/bin make", "make"),
    ('for f in a b; do echo "== $f" && head -5 "$f"; done', "head"),
    ("while true; do sleep 1; done", "true"),
    ("echo '=== tests ==='; ls tests/", "ls"),
    ("sleep 120 && gh pr checks 352", "gh"),
    ("PR=$(gh pr view --json number) && echo $PR", "gh"),
    ("# where is it\nfind /usr/local -name fuse.pc", "find"),
    ("gh api graphql -f query='\nquery {\n  repository { id }\n}'", "gh"),
    ("git add a.py && git commit -m \"$(cat <<'EOF'\nfix: it's done\nEOF\n)\"", "git"),
    ("echo hi", "echo"),
    ("sleep 5", "sleep"),
]


@pytest.mark.parametrize(("command", "program"), CASES)
def test_program_is_the_real_one(command, program):
    assert program_words(command)[0] == program


def test_status_program_skips_leading_setup_line():
    assert status_program("cd /repo\ngrep -q x f") == "grep"


def test_status_program_is_unclear_after_a_loop():
    assert status_program("for f in a; do grep x $f; done") is None


@pytest.mark.parametrize(
    ("command", "subcommand"),
    [
        ("pnpm --filter @cb/sdk exec tsc", "exec"),
        ("git -C /repo status", "status"),
        ("gh pr checks 3 --repo o/r", "pr"),
    ],
)
def test_subcommand_skips_flag_values(command, subcommand):
    assert subcommand_of(command) == subcommand
