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
