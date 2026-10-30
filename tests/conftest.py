import os
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

from airplane import refuse_network

# A git hook (pre-commit runs the unit tests) exports GIT_DIR, GIT_INDEX_FILE and friends, and
# gate scripts export GIT_CONFIG_*. Every `git -C <tmp repo>` in a test would then operate on the
# REAL repository: in a linked worktree the throwaway repos' `git add`, `commit` and `checkout -b`
# landed on the real index and branch and moved the real HEAD. A test must see only its own repo.
LEAKY_GIT_VARIABLES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_PREFIX",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_QUARANTINE_PATH",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
)


REAL_REPO = Path(__file__).resolve().parents[1]
GIT_IDENTITY = "[user]\n\tname = test\n\temail = test@example.com\n"


def pytest_configure(config):
    for name in LEAKY_GIT_VARIABLES:
        os.environ.pop(name, None)
    for name in [n for n in os.environ if n.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))]:
        os.environ.pop(name)
    # git inside tests reads neither the owner's ~/.gitconfig nor /etc/gitconfig: a fixed identity
    # in a temp file, so no test depends on, or can edit, the owner's configuration.
    home = Path(tempfile.mkdtemp(prefix="symbiont-test-gitconfig-"))
    (home / "gitconfig").write_text(GIT_IDENTITY)
    os.environ["GIT_CONFIG_GLOBAL"] = str(home / "gitconfig")
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"


def repo_state(repo: Path) -> str:
    """Repo config and HEAD: what a leaked `git init` or `git config` would change."""
    parts = []
    for command in (["config", "--local", "--list"], ["symbolic-ref", "-q", "HEAD"]):
        out = subprocess.run(["git", "-C", str(repo), *command], capture_output=True, text=True)
        # branch.* and worktree entries change whenever any agent adds a branch; core.*, user.* and
        # extensions.* are the keys that break git for every checkout when they change
        lines = [x for x in out.stdout.splitlines() if x.split(".")[0] not in ("branch", "remote")]
        parts.append(f"$ git {' '.join(command)} -> {out.returncode}\n" + "\n".join(lines) + "\n")
    return "".join(parts)


@pytest.fixture(scope="session", autouse=True)
def real_repository_is_untouched():
    """Fail the session if any test changed the real repo's local config or HEAD (core.bare=true
    once broke every worktree this way: a test's `git init` ran with the hook's GIT_DIR)."""
    before = repo_state(REAL_REPO)
    yield
    after = repo_state(REAL_REPO)
    assert after == before, (
        f"a test changed the real repository:\n--- before\n{before}--- after\n{after}"
    )


@pytest.fixture(autouse=True)
def airplane_mode(request, monkeypatch):
    if request.node.get_closest_marker("periphery"):
        return
    monkeypatch.setattr(socket, "socket", refuse_network)
    monkeypatch.setattr(socket, "create_connection", refuse_network)
