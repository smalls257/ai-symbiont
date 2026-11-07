import pytest

from symbiont.miner.read_only import is_read_only


@pytest.mark.parametrize(
    "command",
    ["git -C /repo status", "git -c core.x=1 log --oneline", "gh --repo o/r pr view 3"],
)
def test_a_flag_value_is_not_read_as_the_subcommand(command):
    assert is_read_only(command) is True


def test_a_write_behind_a_flag_value_is_not_read_only():
    assert is_read_only("git -C /repo config user.email x") is False


def test_a_repo_flag_value_does_not_make_a_write_read_only():
    assert is_read_only("gh --repo o/r pr create --fill") is False


@pytest.mark.parametrize(
    "command",
    ["git status; npm install", "git status && npm install", "ls; git remote add o u",
     "git remote add o u", "git remote remove o", "sed -i -n 1p a", "sed -n -i.bak 1p a",
     "sed --in-place -n 1p a"],
)  # fmt: skip
def test_every_working_segment_must_be_read_only(command):
    assert is_read_only(command) is False


@pytest.mark.parametrize(
    "command",
    ["git status && git log", "git remote", "git remote -v", "git remote show origin",
     "git remote get-url origin", "sed -n 1,5p a.py"],
)  # fmt: skip
def test_read_only_segments_stay_read_only(command):
    assert is_read_only(command) is True
