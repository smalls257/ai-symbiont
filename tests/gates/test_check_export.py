"""scripts/publish/check_export.sh judges the files a push would publish (git archive HEAD), not
history: it is red on a leak that is committed and green on a clean tree."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.periphery


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project(tmp_path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    shutil.copytree(
        REPO / "scripts" / "gates",
        root / "scripts" / "gates",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(REPO / "scripts" / "publish", root / "scripts" / "publish")
    shutil.copytree(REPO / ".semgrep", root / ".semgrep")
    for name in (".gitleaks.toml", "pyproject.toml"):
        shutil.copy(REPO / name, root / name)
    (root / ".venv").symlink_to(REPO / ".venv")
    (root / "src" / "symbiont").mkdir(parents=True)
    (root / "src" / "symbiont" / "ok.py").write_text("x = 1\n")
    (root / "results").mkdir()
    (root / "results" / "r.json").write_text('{"n_runs": 3}\n')
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _check(root: Path, tmp_path: Path):
    terms = tmp_path / "terms.txt"
    terms.write_text("zorbulax\n")
    env = {**os.environ, "SYMBIONT_PRIVATE_TERMS": str(terms)}
    return subprocess.run(
        ["bash", str(root / "scripts" / "publish" / "check_export.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _commit(root: Path, relpath: str, content: str) -> None:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(root, "add", relpath)
    _git(root, "commit", "-q", "-m", "more")


def test_a_clean_export_is_green(project, tmp_path):
    out = _check(project, tmp_path)
    assert out.returncode == 0 and "PUBLISH CHECK GREEN" in out.stdout, out.stdout + out.stderr


@pytest.mark.parametrize(
    ("relpath", "content", "gate"),
    [
        ("src/symbiont/net.py", "HOST = '" + "192.168." + "1.9'\n", "QG-SEC-01"),
        ("docs/n.md", "see /Users/" + "alice" + "/x\n", "QG-SEC-01"),
        ("docs/n.md", "zorbulax lives here\n", "QG-SEC-05"),
        ("data/rows.csv", "a,b\n", "QG-SEC-03"),
        ("results/leak.json", '{"prompt": "hi there friend"}\n', "QG-SEC-04"),
        ("src/symbiont/egress_bypass.py", "import requests\n", "QG-SAST-02"),
    ],
)
def test_a_committed_leak_turns_the_export_red_on_the_right_gate(
    project, tmp_path, relpath, content, gate
):
    _commit(project, relpath, content)
    out = _check(project, tmp_path)
    assert out.returncode == 1 and f"FAIL  {gate}" in out.stdout, out.stdout + out.stderr


def test_an_uncommitted_leak_is_not_exported_so_the_message_says_commit_first(project, tmp_path):
    (project / "docs").mkdir()
    (project / "docs" / "n.md").write_text("zorbulax\n")
    assert _check(project, tmp_path).returncode == 0


def test_export_ignore_cannot_hide_a_tracked_file_and_is_itself_a_finding(project, tmp_path):
    _commit(project, "data/rows.csv", "a,b\n")
    _commit(project, ".gitattributes", "data export-ignore\n")
    out = _check(project, tmp_path)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "FAIL  QG-PUB-01" in out.stdout and "export-ignore" in out.stdout
    assert "FAIL  QG-SEC-03" in out.stdout and "data/rows.csv" in out.stdout


def test_a_gate_file_that_differs_from_head_refuses_the_run(project, tmp_path):
    _commit(project, "src/symbiont/net.py", "HOST = '" + "192.168." + "1.9'\n")
    config = project / ".gitleaks.toml"
    config.write_text(config.read_text() + "\n# loosened locally\n")
    out = _check(project, tmp_path)
    assert (
        out.returncode == 1 and "differ from HEAD" in out.stderr and ".gitleaks.toml" in out.stderr
    )


def test_the_committed_config_judges_the_commit_not_the_working_copy(project, tmp_path):
    _commit(project, "src/symbiont/net.py", "HOST = '" + "192.168." + "1.9'\n")
    (project / "scripts" / "gates" / "check_paths.sh").write_text("exit 0\n")
    assert _check(project, tmp_path).returncode == 1


def test_an_export_without_src_is_a_failure_not_a_pass(project, tmp_path):
    _git(project, "rm", "-q", "-r", "src")
    _git(project, "commit", "-q", "-m", "drop src")
    out = _check(project, tmp_path)
    assert out.returncode == 1 and "no src/" in out.stdout


@pytest.mark.parametrize("name", ["données.parquet", "my data/rows.csv", "KEYS.PEM"])
def test_awkward_and_upper_case_names_turn_the_export_red(project, tmp_path, name):
    _commit(project, name, "x\n")
    out = _check(project, tmp_path)
    assert out.returncode == 1 and "FAIL  QG-SEC-03" in out.stdout


def test_a_results_sentence_under_an_unlisted_key_turns_the_export_red(project, tmp_path):
    _commit(project, "results/r2.json", '{"problem_statement": "Fix bug in the join"}\n')
    out = _check(project, tmp_path)
    assert out.returncode == 1 and "FAIL  QG-SEC-04" in out.stdout
