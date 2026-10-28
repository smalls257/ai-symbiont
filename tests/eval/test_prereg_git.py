"""require_frozen against a real throwaway git repo, and the scored-run switch."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from symbiont.eval.prereg import PreregNotFrozenError
from symbiont.eval.prereg_git import EXPLORATORY, SCORED, require_frozen, run_provenance

pytestmark = pytest.mark.periphery

ORIGINAL = "2026-10-27-run.md"
AMENDMENT_NAME = "2026-10-28-run-fix.md"
GOOD = (
    "# Pre-registration: a run\n\n**FROZEN 2026-10-27.** Committed alone.\n\n"
    "Claim tags: [measured]\n"
)
AMENDMENT = (
    "# Amendment to the run\n\n**FROZEN 2026-10-28.** Fix.\n\n"
    f"Amends: prereg/{ORIGINAL}\n\nClaim tags: [measured]\n"
)


def git(repo: Path, *args: str) -> str:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") or k.startswith("GIT_CONFIG_GLOBAL")
    }
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "prereg").mkdir(parents=True)
    git(root, "init", "-q")
    return root


def commit(repo: Path, name: str, text: str) -> str:
    (repo / "prereg" / name).write_text(text)
    git(repo, "add", f"prereg/{name}")
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


def test_a_committed_unchanged_prereg_is_frozen(repo):
    sha = commit(repo, ORIGINAL, GOOD)
    frozen = require_frozen(repo / "prereg" / ORIGINAL)
    assert frozen.commit == sha
    assert frozen.sha256 == hashlib.sha256(GOOD.encode()).hexdigest()


def test_an_untracked_prereg_is_refused(repo):
    (repo / "prereg" / ORIGINAL).write_text(GOOD)
    with pytest.raises(PreregNotFrozenError, match=f"{ORIGINAL}.*untracked"):
        require_frozen(repo / "prereg" / ORIGINAL)


def test_a_modified_prereg_is_refused(repo):
    commit(repo, ORIGINAL, GOOD)
    (repo / "prereg" / ORIGINAL).write_text(GOOD + "\nedited after the freeze\n")
    with pytest.raises(PreregNotFrozenError, match="modified in the working tree"):
        require_frozen(repo / "prereg" / ORIGINAL)


def test_a_staged_but_uncommitted_edit_is_refused(repo):
    commit(repo, ORIGINAL, GOOD)
    (repo / "prereg" / ORIGINAL).write_text(GOOD + "\nedited\n")
    git(repo, "add", f"prereg/{ORIGINAL}")
    with pytest.raises(PreregNotFrozenError, match="staged but not committed"):
        require_frozen(repo / "prereg" / ORIGINAL)


def test_a_staged_new_file_is_refused(repo):
    (repo / "prereg" / ORIGINAL).write_text(GOOD)
    git(repo, "add", f"prereg/{ORIGINAL}")
    with pytest.raises(PreregNotFrozenError, match="staged but not committed"):
        require_frozen(repo / "prereg" / ORIGINAL)


def test_a_missing_file_and_a_non_repo_are_refused(repo, tmp_path):
    with pytest.raises(PreregNotFrozenError, match="no such file"):
        require_frozen(repo / "prereg" / "nope.md")
    loose = tmp_path / "loose.md"
    loose.write_text(GOOD)
    with pytest.raises(PreregNotFrozenError, match="loose.md"):
        require_frozen(loose)


def test_the_amendment_chain_needs_every_link_frozen(repo):
    commit(repo, ORIGINAL, GOOD)
    amendment_sha = commit(repo, AMENDMENT_NAME, AMENDMENT)
    frozen = require_frozen(repo / "prereg" / AMENDMENT_NAME)
    assert (frozen.commit, frozen.original.name) == (amendment_sha, ORIGINAL)
    (repo / "prereg" / ORIGINAL).write_text(GOOD + "\nedited\n")
    with pytest.raises(PreregNotFrozenError, match=ORIGINAL):
        require_frozen(repo / "prereg" / AMENDMENT_NAME)


def test_scored_without_a_prereg_refuses():
    with pytest.raises(PreregNotFrozenError, match="--scored needs --prereg"):
        run_provenance(scored=True, prereg=None, expects=ORIGINAL)


def test_a_prereg_without_scored_refuses():
    with pytest.raises(PreregNotFrozenError, match="without --scored"):
        run_provenance(scored=False, prereg="prereg/x.md", expects=ORIGINAL)


def test_an_unscored_run_is_labeled_exploratory():
    fields = run_provenance(scored=False, prereg=None, expects=ORIGINAL)
    assert fields["run_label"] == EXPLORATORY and fields["prereg_sha256"] is None


def test_a_prereg_registered_for_another_runner_is_refused(repo):
    commit(repo, "2026-10-27-other.md", GOOD)
    with pytest.raises(PreregNotFrozenError, match="registered under"):
        run_provenance(
            scored=True, prereg=str(repo / "prereg" / "2026-10-27-other.md"), expects=ORIGINAL
        )


def test_the_hash_and_commit_reach_json_the_results_gate_accepts(repo):
    sha = commit(repo, ORIGINAL, GOOD)
    fields = run_provenance(scored=True, prereg=str(repo / "prereg" / ORIGINAL), expects=ORIGINAL)
    assert fields["run_label"] == SCORED
    assert fields["freeze_commit"] == sha
    assert fields["prereg_sha256"] == hashlib.sha256(GOOD.encode()).hexdigest()
    out = repo / "result.json"
    out.write_text(json.dumps(fields))
    gate = Path(__file__).resolve().parents[2] / "scripts/gates/check_results_content.py"
    subprocess.run(["python3", str(gate), str(out)], check=True, capture_output=True)
