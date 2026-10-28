"""QG-GATE-01: a gate cannot be loosened by the commit that needs it.

Each test builds a throwaway repo with a base commit on `main`, then changes a protected file
on a branch and asks the check what it sees."""

import subprocess
from pathlib import Path

import pytest

from gate_loader import load_gate

integrity = load_gate("check_gate_integrity")

PYPROJECT = '[project]\nname = "x"\ndependencies = []\n\n[tool.ruff]\nline-length = 100\n'


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, ".lizard-whitelist.txt", "# header\nsrc/a.py:old  # me, why, expires 2099-01-01\n")
    _write(root, ".naming-waivers.txt", "# header\n")
    _write(root, "scripts/gates/test-floor.txt", "240  # ratchet\n")
    _write(root, "scripts/gates/run.sh", "echo gate\n")
    _write(root, "pyproject.toml", PYPROJECT)
    _write(root, "src/a.py", "x = 1\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "work")
    monkeypatch.chdir(root)
    monkeypatch.setenv("SYMBIONT_GATE_BASE", "main")
    return root


def _found(root: Path) -> list[str]:
    return integrity.violations(root, integrity.base_commit(root))


def test_an_untouched_tree_is_clean(repo):
    assert _found(repo) == []


def test_adding_a_waiver_is_caught_removing_one_is_not(repo):
    _write(repo, ".naming-waivers.txt", "src/a.py:handle_it  # me, why, expires 2099-01-01\n")
    assert any("waiver added" in v for v in _found(repo))
    _write(repo, ".naming-waivers.txt", "# header\n")
    _write(repo, ".lizard-whitelist.txt", "# header\n")
    assert _found(repo) == []


def test_lowering_the_floor_is_caught_raising_it_is_not(repo):
    _write(repo, "scripts/gates/test-floor.txt", "100  # lowered\n")
    assert any("floor lowered" in v for v in _found(repo))
    _write(repo, "scripts/gates/test-floor.txt", "300  # raised\n")
    assert [v for v in _found(repo) if "floor" in v] == []


def test_changing_a_gate_script_or_config_is_caught(repo):
    _write(repo, "scripts/gates/run.sh", "echo looser\n")
    _write(repo, ".gitleaks.toml", "title = 'new'\n")
    found = _found(repo)
    assert any("scripts/gates/run.sh" in v for v in found)
    assert any(".gitleaks.toml" in v for v in found)


def test_only_the_tool_tables_of_pyproject_are_protected(repo):
    _write(
        repo, "pyproject.toml", PYPROJECT.replace("dependencies = []", 'dependencies = ["numpy"]')
    )
    assert _found(repo) == []
    _write(repo, "pyproject.toml", PYPROJECT.replace("100", "300"))
    assert any("pyproject.toml" in v for v in _found(repo))


def test_a_deleted_gate_file_is_a_violation(repo):
    (repo / "scripts/gates/run.sh").unlink()
    assert any("deleted" in v for v in _found(repo))


def _commit(root: Path, path: str, text: str, message: str) -> str:
    _write(root, path, text)
    _git(root, "add", path)
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD").strip()


def test_a_marked_commit_may_loosen_its_own_change(repo):
    _commit(repo, "scripts/gates/run.sh", "echo looser\n", "tighten\n\nGATE-CHANGE: owner approved")
    assert integrity.main([]) == 0


def test_a_later_unmarked_commit_fails_even_after_a_marked_one(repo, capsys):
    _commit(repo, "scripts/gates/run.sh", "echo looser\n", "tighten\n\nGATE-CHANGE: owner approved")
    late = _commit(
        repo,
        ".naming-waivers.txt",
        "src/a.py:handle_it  # me, why, expires 2099-01-01\n",
        "quiet it",
    )
    assert integrity.main([]) == 1
    err = capsys.readouterr().err
    assert late[:10] in err and "waiver added" in err


def test_an_unmarked_commit_that_only_tightens_is_fine(repo):
    _commit(repo, ".lizard-whitelist.txt", "# header\n", "remove the waiver")
    _commit(repo, "scripts/gates/test-floor.txt", "300\n", "raise the floor")
    assert integrity.main([]) == 0


def test_the_owner_ledger_accepts_a_named_commit(repo):
    sha = _commit(repo, "scripts/gates/run.sh", "echo older\n", "before the trailer existed")
    assert integrity.main([]) == 1
    _write(repo, integrity.LEDGER, f"{sha}  # accepted by the owner\n")
    assert [
        v for v in integrity.unmarked_commits(repo, integrity.base_commit(repo)) if sha[:10] in v
    ] == []


def test_the_report_lists_every_marked_commit_with_reason_and_files(repo, capsys):
    sha = _commit(repo, "scripts/gates/run.sh", "echo x\n", "x\n\nGATE-CHANGE: raise caps")
    _commit(repo, "src/a.py", "y = 2\n", "ordinary change")
    assert integrity.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert sha[:10] in out and "raise caps" in out and "scripts/gates/run.sh" in out
    assert "ordinary change" not in out


def test_main_exit_codes(repo, tmp_path, capsys):
    assert integrity.main([]) == 0
    _write(repo, "scripts/gates/test-floor.txt", "1\n")
    assert integrity.main([]) == 1
    message = tmp_path / "msg"
    message.write_text("lower floor\n\nGATE-CHANGE: owner decision\n")
    assert integrity.main(["--message-file", str(message)]) == 0
    message.write_text("lower floor\n\nGATE-CHANGE:\n")  # an empty reason does not count
    assert integrity.main(["--message-file", str(message)]) == 1


def test_an_unknown_base_is_an_error_not_a_pass(repo, monkeypatch):
    monkeypatch.setenv("SYMBIONT_GATE_BASE", "no-such-ref")
    with pytest.raises(integrity.IntegrityError):
        integrity.main([])


def _main_moves_on(root: Path, path: str, text: str) -> None:
    _git(root, "checkout", "-q", "main")
    _commit(root, path, text, "approved on main\n\nGATE-CHANGE: owner approved")
    _git(root, "checkout", "-q", "work")


def test_merging_main_with_its_approved_gate_change_passes_pending_and_committed(repo):
    _commit(repo, "src/a.py", "x = 2\n", "branch work")
    _main_moves_on(repo, "scripts/gates/run.sh", "echo stricter\n")
    _git(repo, "merge", "-q", "--no-commit", "--no-ff", "main")
    assert integrity.main([]) == 0
    _git(repo, "commit", "-q", "-m", "merge main")
    assert integrity.main([]) == 0


def test_a_merge_resolution_that_writes_new_gate_content_fails(repo, capsys):
    _commit(repo, "src/a.py", "x = 2\n", "branch work")
    _main_moves_on(repo, "scripts/gates/run.sh", "echo stricter\n")
    _git(repo, "merge", "-q", "--no-commit", "--no-ff", "main")
    _write(repo, "scripts/gates/run.sh", "echo something else\n")
    _git(repo, "add", "scripts/gates/run.sh")
    assert integrity.main([]) == 1
    assert "run.sh" in capsys.readouterr().err


def test_a_merge_keeping_the_branch_approved_gate_change_passes(repo):
    _commit(repo, "scripts/gates/run.sh", "echo mine\n", "mine\n\nGATE-CHANGE: owner approved")
    _main_moves_on(repo, "src/a.py", "x = 3\n")
    _git(repo, "merge", "-q", "--no-edit", "main")
    assert integrity.main([]) == 0


def test_merging_a_branch_that_is_not_main_gets_no_relief(repo):
    _git(repo, "checkout", "-q", "-b", "side", "main")
    _commit(repo, ".naming-waivers.txt", "src/a.py:handle_it  # me, why, 2099-01-01\n", "sneak")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "-q", "--no-commit", "--no-ff", "side")
    assert integrity.main([]) == 1


def test_a_merge_that_lowers_main_floor_in_resolution_fails(repo):
    _main_moves_on(repo, "scripts/gates/test-floor.txt", "300  # ratchet\n")
    _commit(repo, "scripts/gates/test-floor.txt", "260  # ratchet\n", "raise\n\nGATE-CHANGE: ok")
    conflicted = subprocess.run(["git", "-C", str(repo), "merge", "-q", "main"], check=False)
    assert conflicted.returncode != 0
    _write(repo, "scripts/gates/test-floor.txt", "250  # ratchet\n")
    _git(repo, "add", "scripts/gates/test-floor.txt")
    assert integrity.main([]) == 1
