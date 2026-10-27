"""QG-SEC-05: the owner's identifiers are found without being written into a tracked file."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = str(REPO / "scripts" / "gates" / "check_private_terms.py")

pytestmark = pytest.mark.periphery


def _run(terms: Path | None, *args: str, cwd: Path):
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(cwd),
        "SYMBIONT_PRIVATE_TERMS": str(terms or cwd / "absent"),
    }
    return subprocess.run(
        [sys.executable, SCRIPT, *args], cwd=cwd, env=env, capture_output=True, text=True
    )


def _git(repo, *args):
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "-C", str(repo), *identity, *args], check=True, capture_output=True)


@pytest.fixture
def terms(tmp_path) -> Path:
    path = tmp_path / "terms.txt"
    path.write_text("# comment\nZorbulax\nnickname-q\n")
    return path


def test_a_term_fires_case_insensitively_and_the_log_never_repeats_it(tmp_path, terms):
    (tmp_path / "a.txt").write_text("fine\nowner is zORBULAX here\n")
    out = _run(terms, "files", "a.txt", cwd=tmp_path)
    assert out.returncode == 1 and "a.txt:2" in out.stderr
    assert "zorbulax" not in (out.stderr + out.stdout).lower()


def test_a_clean_file_passes(tmp_path, terms):
    (tmp_path / "a.txt").write_text("nothing personal\n")
    assert _run(terms, "files", "a.txt", cwd=tmp_path).returncode == 0


def test_a_path_that_holds_a_term_fires(tmp_path, terms):
    (tmp_path / "tree" / "zorbulax").mkdir(parents=True)
    (tmp_path / "tree" / "zorbulax" / "a.txt").write_text("clean\n")
    assert _run(terms, "tree", str(tmp_path / "tree"), cwd=tmp_path).returncode == 1


def test_no_terms_file_fails_closed(tmp_path):
    out = _run(None, "files", "a.txt", cwd=tmp_path)
    assert out.returncode == 2 and "no private-terms file" in out.stderr


def test_an_empty_or_too_short_terms_file_fails_closed(tmp_path):
    empty = tmp_path / "t.txt"
    empty.write_text("# only a comment\n")
    assert _run(empty, "files", "a.txt", cwd=tmp_path).returncode == 2
    empty.write_text("ab\n")
    assert _run(empty, "files", "a.txt", cwd=tmp_path).returncode == 2


def test_staged_mode_sees_only_added_lines(tmp_path, terms):

    def git(*args):
        identity = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run(
            ["git", "-C", str(tmp_path), *identity, *args], check=True, capture_output=True
        )

    git("init", "-q")
    (tmp_path / "a.txt").write_text("zorbulax was here\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "old")
    (tmp_path / "a.txt").write_text("zorbulax was here\nnew clean line\n")
    git("add", "a.txt")
    assert _run(terms, "staged", cwd=tmp_path).returncode == 0
    (tmp_path / "b.txt").write_text("a Zorbulax line\n")
    git("add", "b.txt")
    assert _run(terms, "staged", cwd=tmp_path).returncode == 1


@pytest.mark.parametrize("name", ["é.md", "my notes.md", "données/ñ.md", 'quo"te.md'])
def test_staged_mode_scans_files_with_awkward_names(tmp_path, terms, name):
    def git(*args):
        identity = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run(
            ["git", "-C", str(tmp_path), *identity, *args], check=True, capture_output=True
        )

    git("init", "-q")
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("a Zorbulax line\n")
    git("add", "--", name)
    out = _run(terms, "staged", cwd=tmp_path)
    assert out.returncode == 1 and ":1:" in out.stderr


def test_files0_reads_nul_delimited_names_from_stdin(tmp_path, terms):
    (tmp_path / "my notes.md").write_text("zorbulax\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "SYMBIONT_PRIVATE_TERMS": str(terms)}
    out = subprocess.run(
        [sys.executable, SCRIPT, "files0"],
        input=b"my notes.md\0",
        cwd=tmp_path,
        env=env,
        capture_output=True,
    )
    assert out.returncode == 1 and b"my notes.md:1" in out.stderr


def test_a_terms_file_readable_by_others_warns_without_failing(tmp_path, terms):
    (tmp_path / "a.txt").write_text("clean\n")
    terms.chmod(0o644)
    loose = _run(terms, "files", "a.txt", cwd=tmp_path)
    terms.chmod(0o600)
    tight = _run(terms, "files", "a.txt", cwd=tmp_path)
    assert loose.returncode == 0 and "chmod 600" in loose.stderr
    assert tight.returncode == 0 and "chmod 600" not in tight.stderr


@pytest.mark.parametrize(
    "line",
    [
        "++ Zorbulax",
        "+++ Zorbulax",
        "++++ b/x Zorbulax",
        "+ Zorbulax",
        "--- a/x Zorbulax",
        "diff --git a/x b/Zorbulax",
        "@@ -1 +1 @@ Zorbulax",
    ],
)
def test_staged_lines_that_look_like_diff_markers_are_still_scanned(tmp_path, terms, line):
    _git(tmp_path, "init", "-q")
    (tmp_path / "base.txt").write_text("clean\n")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "patch.txt").write_text(f"clean\n{line}\n")
    _git(tmp_path, "add", "patch.txt")
    out = _run(terms, "staged", cwd=tmp_path)
    assert out.returncode == 1 and "patch.txt:" in out.stderr


def test_a_term_inside_a_committed_patch_text_is_found(tmp_path, terms):
    _git(tmp_path, "init", "-q")
    patch = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new Zorbulax\n"
    (tmp_path / "changes.patch").write_text(patch)
    _git(tmp_path, "add", "changes.patch")
    out = _run(terms, "staged", cwd=tmp_path)
    assert out.returncode == 1 and "changes.patch:" in out.stderr


def test_added_lines_of_skips_only_the_file_header():
    from importlib import util

    spec = util.spec_from_file_location("terms_gate", SCRIPT)
    gate = util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    patch = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -0,0 +1,3 @@\n+a\n++b\n+++c\n"
    assert gate.added_lines_of(patch) == ["a", "+b", "++c"]
