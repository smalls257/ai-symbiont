"""A test never inherits the git environment of the hook that launched it (Infected Core for the
whole suite: one leaked GIT_INDEX_FILE and a test's `git add` rewrites the real index)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import LEAKY_GIT_VARIABLES, repo_state

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.periphery


def test_the_hook_git_variables_are_gone_inside_the_suite():
    assert [name for name in LEAKY_GIT_VARIABLES if name in os.environ] == []
    assert [name for name in os.environ if name.startswith("GIT_CONFIG_KEY_")] == []


def test_a_polluted_environment_is_scrubbed_before_the_first_test(tmp_path):
    """Re-run the first test in a nested pytest whose environment looks like a hook's."""
    decoy = tmp_path / "decoy-index"
    decoy.write_text("decoy")
    env = {
        **os.environ,
        "GIT_INDEX_FILE": str(decoy),
        "GIT_DIR": str(tmp_path / "decoy.git"),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.quotePath",
        "GIT_CONFIG_VALUE_0": "false",
    }
    target = f"{Path(__file__)}::test_the_hook_git_variables_are_gone_inside_the_suite"
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
        cwd=REPO, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert out.returncode == 0, out.stdout + out.stderr
    assert decoy.read_text() == "decoy"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_the_repository_state_snapshot_notices_a_config_or_head_change(tmp_path):
    _git(tmp_path, "init", "-q")
    before = repo_state(tmp_path)
    assert repo_state(tmp_path) == before
    _git(tmp_path, "config", "core.bare", "true")
    assert repo_state(tmp_path) != before


def test_git_inside_tests_uses_the_fixed_identity_not_the_owners_config(tmp_path):
    _git(tmp_path, "init", "-q")
    name = subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name"], capture_output=True, text=True
    )
    assert name.stdout.strip() == "test"
