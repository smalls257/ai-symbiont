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


@pytest.mark.parametrize(
    "command",
    ["[ -f x ] && git status", "if [ -f x ]; then ls; fi", "while read l; do echo $l; done < f",
     "[[ -d a ]] && ls", "test -f x && git log", "git status | sort", "ls | sort | uniq",
     "git diff | cut -d' ' -f1 | tr a b | column -t", "git log | head -5 | jq ."],
)  # fmt: skip
def test_guards_loops_and_filter_stages_stay_read_only(command):
    assert is_read_only(command) is True


@pytest.mark.parametrize("command", ["ls | xargs rm", "git status; npm install", "ls | tee out"])
def test_a_later_stage_that_acts_is_not_a_filter(command):
    assert is_read_only(command) is False


def test_a_filter_is_only_a_filter_after_a_read_only_first_stage():
    assert is_read_only("npm install | sort") is False
    assert is_read_only("git status; sort") is False
