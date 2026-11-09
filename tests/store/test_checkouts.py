"""The names a repository's checkouts go by: the registered one, its git worktrees, its siblings.

Failure guarded against: edits made in a worktree or a sibling checkout (`<project>-feature`)
counted as outside the codebase, so a fix made there never became a lesson.
"""

import subprocess
from pathlib import Path

import pytest

from record_builders import edit, run, session
from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.store.checkouts import checkout_names, names_for
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "planner"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "commit", "-q", "--allow-empty", "-m", "start")
    return repo


def test_the_checkout_its_git_worktrees_and_its_siblings_are_all_the_codebase(tmp_path, checkout):
    git(checkout, "worktree", "add", "-q", str(tmp_path / "elsewhere" / "scratchpad"), "-b", "w")
    (tmp_path / "planner-experiment").mkdir()
    (tmp_path / "unrelated").mkdir()

    names = checkout_names(checkout)

    assert names == {"planner", "scratchpad", "planner-experiment"}


def test_a_directory_that_is_not_a_git_repository_still_names_itself_and_its_siblings(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (tmp_path / "plain-two").mkdir()

    assert checkout_names(plain) == {"plain", "plain-two"}


def test_a_checkout_that_went_missing_names_nothing_rather_than_guessing(tmp_path):
    assert checkout_names(tmp_path / "gone") == frozenset()


def test_the_registered_checkout_is_remembered_for_later_minings(tmp_path, checkout):
    registry = RepoRegistry(tmp_path / "data")
    registry.record_stance("planner", RepoStance.GIVEN)
    assert names_for(registry, "planner") == frozenset()

    registry.record_checkout("planner", checkout)

    assert names_for(registry, "planner") == {"planner"}
    assert RepoRegistry(tmp_path / "data").checkout("planner") == checkout


def test_a_fix_made_in_a_sibling_checkout_is_a_code_fix_once_the_names_are_fed(tmp_path, checkout):
    (tmp_path / "planner-experiment").mkdir()
    steps = session(
        run(
            "pytest tests/test_a.py", 1, "File \"app/a.py\", line 1\nImportError: cannot import 'a'"
        ),
        edit("/home/dev/planner-experiment/app/a.py", diff="-a\n+def a():\n"),
        run("pytest tests/test_a.py", 0, "1 passed"),
    )
    mined = mine_history(sessions_of(steps), {})

    (alone,) = lessons_from(mined, steps, frozenset({"planner"}))
    (fed,) = lessons_from(mined, steps, checkout_names(checkout))

    assert alone.fix is None and fed.fix is FixKind.CODE_FIX
