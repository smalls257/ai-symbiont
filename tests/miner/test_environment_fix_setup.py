import pytest

from symbiont.miner.environment_fix import setup_command
from symbiont.records.schema import Kind, Provenance, Record


def _command(step, text, exit_code):
    return Record(
        harness="h", project="p", session_id="s1", step=step, kind=Kind.COMMAND, raw="boom",
        provenance=Provenance("t", "x", True), command=text, exit_code=exit_code,
    )  # fmt: skip


def _between(text):
    records = [
        _command(1, "pytest tests/test_a.py", 1),
        _command(2, text, 0),
        _command(3, "pytest tests/test_a.py", 0),
    ]
    return setup_command(records[0], records)


@pytest.mark.parametrize(
    "text",
    [
        "cd /repo",
        "echo x",
        "git log --oneline -2; git status --short",
        "gh pr view 3",
        "gh api repos/o/r/pulls",
        "sleep 5",
        "npm --version",
        "export A=1",
        "git branch",
        "git stash list",
        "git add a.ts",
        "jq . x.json",
        "sed -n 1,5p a.py",
        "sleep 5 && git diff",
    ],
)
def test_plumbing_and_read_only_commands_are_no_setup(text):
    assert _between(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "npm install",
        "docker compose up -d",
        "git config user.email x",
        "git branch feature",
        "gh api repos/o/r/issues -f title",
        "gh api repos/o/r -X DELETE",
        "kill 123",
    ],
)
def test_installs_and_writes_are_setup(text):
    assert _between(text) == text


def test_the_working_line_is_named_not_the_first():
    assert _between("cd /repo\nnpm install") == "npm install"
