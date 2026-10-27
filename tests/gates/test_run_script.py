"""run.sh itself: exit codes and wiring, driven in a throwaway repo.

A gate runner that reports GREEN when it could not run is a Paper Tiger, so every way the
runner can be unable to run (bad base ref, missing tool, missing venv) must be non-zero, a
planted violation must turn the right gates red, and a clean tree must be green."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COPIED = (".gitleaks.toml", ".importlinter", ".naming-waivers.txt", ".lizard-whitelist.txt")

pytestmark = pytest.mark.periphery


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


def _copy_gate_tooling(root: Path) -> None:
    shutil.copytree(
        REPO / "scripts" / "gates",
        root / "scripts" / "gates",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(REPO / ".semgrep", root / ".semgrep")
    shutil.copytree(REPO / "scripts" / "hooks", root / "scripts" / "hooks")
    for name in (*COPIED, "pyproject.toml", "uv.lock", ".gitleaks-baseline.json"):
        shutil.copy(REPO / name, root / name)
    (root / "scripts/gates/test-floor.txt").write_text("1\n")
    (root / ".gitleaks-baseline.json").write_text("[]\n")


@pytest.fixture
def gate_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "src" / "symbiont").mkdir(parents=True)
    (root / "src/symbiont/__init__.py").write_text('"""Package."""\n')
    (root / "tests/test_ok.py").write_text("def test_it_runs():\n    assert 1 + 1 == 2\n")
    _copy_gate_tooling(root)
    (root / ".venv").symlink_to(REPO / ".venv")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-f", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "work")
    return root


def _run(root: Path, *, path: str | None = None, **env: str):
    terms = root.parent / "private-terms.txt"
    terms.write_text("zorbulax\n")
    # the outer run's base ref and stage name a different repo; only an explicit override passes in
    outer = {
        k: v
        for k, v in os.environ.items()
        if k not in ("SYMBIONT_GATE_STAGE", "SYMBIONT_GATE_BASE")
    }
    environment = {**outer, "SYMBIONT_PRIVATE_TERMS": str(terms), **env}
    if path is not None:
        environment["PATH"] = path
    return subprocess.run(
        ["bash", str(root / "scripts/gates/run.sh"), "fast"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_clean_tree_is_green(gate_repo):
    out = _run(gate_repo)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.rstrip().endswith("GREEN")


def test_a_bad_base_ref_is_an_error_never_green(gate_repo):
    out = _run(gate_repo, SYMBIONT_GATE_BASE="no-such-ref")
    assert out.returncode == 2
    assert "GREEN" not in out.stdout and "no-such-ref" in out.stderr


def test_a_missing_tool_is_an_error(gate_repo, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").symlink_to(shutil.which("uv"))
    out = _run(gate_repo, path=f"{bin_dir}:/usr/bin:/bin")
    assert out.returncode == 2
    assert "gitleaks" in out.stderr and "GREEN" not in out.stdout


def test_a_missing_private_terms_file_turns_the_run_red_not_green(gate_repo, tmp_path):
    out = _run(gate_repo, SYMBIONT_PRIVATE_TERMS=str(tmp_path / "absent.txt"))
    assert out.returncode == 1 and "QG-SEC-05" in out.stdout and "GREEN" not in out.stdout


def test_a_missing_venv_says_how_to_fix_it(gate_repo):
    (gate_repo / ".venv").unlink()
    out = _run(gate_repo)
    assert out.returncode == 2
    assert "uv sync --group dev" in out.stderr


def test_a_missing_config_is_an_error(gate_repo):
    (gate_repo / ".gitleaks-baseline.json").unlink()
    assert _run(gate_repo).returncode == 2


def test_planted_violations_turn_the_matching_gates_red(gate_repo):
    bad = gate_repo / "src/symbiont/core/bad.py"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "import socket\n\n\ndef handle_it(rows, strict: bool, loud: bool):\n    return rows\n"
    )
    (gate_repo / "data").mkdir()
    (gate_repo / "data/rows.csv").write_text("a,b\n")
    _git(gate_repo, "add", "-f", "data/rows.csv")
    (gate_repo / "scripts/gates/test-floor.txt").write_text("0\n")
    out = _run(gate_repo)
    assert out.returncode == 1, out.stdout + out.stderr
    for gate in ("QG-SEC-03", "QG-RD-02", "QG-SAST-02", "QG-GATE-01"):
        assert f"FAIL  {gate}" in out.stdout, gate
    assert "RED:" in out.stdout and "GREEN" not in out.stdout


PRIVACY_GATES = ("QG-SEC-01", "QG-SEC-03", "QG-SEC-04", "QG-SEC-05")


def test_the_pre_commit_hook_really_runs_every_privacy_gate(gate_repo):
    """The installed hook, not just run.sh: a gate nobody calls is a Paper Tiger."""
    (gate_repo / "src" / "symbiont" / "a.py").write_text('"""A module."""\n')
    _git(gate_repo, "add", "src/symbiont/a.py")
    terms = gate_repo.parent / "private-terms.txt"
    terms.write_text("zorbulax\n")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("SYMBIONT_GATE_STAGE", "SYMBIONT_GATE_BASE")
    }
    env["SYMBIONT_PRIVATE_TERMS"] = str(terms)
    hook = subprocess.run(
        ["bash", str(gate_repo / "scripts/hooks/pre-commit")],
        cwd=gate_repo, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    # the throwaway repo has no boundary tests, so QG-TST-02 may be red;
    # exit 2 would mean a gate could not run
    assert hook.returncode in (0, 1), hook.stdout + hook.stderr
    lines = (gate_repo / ".gate-runs.jsonl").read_text().splitlines()
    ran = {json.loads(line)["gate"] for line in lines if json.loads(line)["stage"] == "pre-commit"}
    assert set(PRIVACY_GATES) <= ran, sorted(set(PRIVACY_GATES) - ran)


def test_the_hooks_call_run_sh_in_the_right_mode_and_every_gate_is_wired():
    hooks = REPO / "scripts" / "hooks"
    pre_commit, pre_push = (hooks / "pre-commit").read_text(), (hooks / "pre-push").read_text()
    assert (
        "SYMBIONT_GATE_STAGE=pre-commit" in pre_commit and "scripts/gates/run.sh fast" in pre_commit
    )
    assert "scripts/gates/run.sh full" in pre_push
    assert "check_gate_integrity.py --message-file" in (hooks / "commit-msg").read_text()
    for hook in ("pre-commit", "commit-msg", "pre-push"):
        assert os.access(hooks / hook, os.X_OK), f"{hook} is not executable"
    run_sh = (REPO / "scripts" / "gates" / "run.sh").read_text()
    for gate in (*PRIVACY_GATES, "QG-SEC-02", "QG-GATE-01", "QG-SAST-02"):
        assert f"gate {gate} " in run_sh, f"run.sh never runs {gate}"
    installer = (REPO / "scripts" / "install-hooks.sh").read_text()
    assert "git config core.hooksPath scripts/hooks" in installer


def test_the_installed_hooks_path_points_at_the_tracked_hooks():
    out = subprocess.run(
        ["git", "-C", str(REPO), "config", "--get", "core.hooksPath"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert out.stdout.strip() == "scripts/hooks", (
        "hooks are not armed: run scripts/install-hooks.sh"
    )
