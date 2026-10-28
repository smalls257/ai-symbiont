"""The gates wired after phase 1 (QG-TYP-03, QG-DEP-01, QG-DEP-02, QG-RD-01, QG-TST-03).

Each test plants the violation the gate exists to stop and expects red, and a clean case
expects green: a gate that cannot fail is a Paper Tiger."""

import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATES = REPO / "scripts" / "gates"
sys.path.insert(0, str(GATES))

import check_audit  # noqa: E402
import check_licenses  # noqa: E402
import check_type_ignores  # noqa: E402

TODAY = date(2026, 10, 27)


def test_a_bare_type_ignore_is_refused_and_a_reasoned_one_is_counted():
    source = "a = f()  # type: ignore\nb = f()  # type: ignore[arg-type] # vizdoom stubs lag\n"
    total, problems = check_type_ignores.audit_source(source, "x.py")
    assert total == 2
    assert len(problems) == 1 and problems[0].startswith("x.py:1:")


def test_a_type_ignore_inside_a_string_is_not_a_comment():
    assert check_type_ignores.ignores_in('s = "# type: ignore"\n', "x.py") == []


def test_the_ceiling_is_a_ratchet_not_a_suggestion(tmp_path, monkeypatch):
    monkeypatch.setattr(check_type_ignores, "ROOT", tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("x = 1  # type: ignore[misc] # why\n")
    ceiling = tmp_path / "ceiling.txt"
    ceiling.write_text("0\n")
    monkeypatch.setattr(check_type_ignores, "CEILING_FILE", ceiling)
    monkeypatch.setattr(check_type_ignores, "tracked_python", lambda: ["src/a.py"])
    assert check_type_ignores.main(["check"]) == 1
    ceiling.write_text("1\n")
    assert check_type_ignores.main(["check"]) == 0


def test_a_missing_ceiling_cannot_judge(tmp_path, monkeypatch):
    monkeypatch.setattr(check_type_ignores, "CEILING_FILE", tmp_path / "absent.txt")
    assert check_type_ignores.main(["check"]) == 2


@pytest.mark.parametrize(
    "expression",
    ["MIT", "BSD License", "Apache-2.0 OR BSD-3-Clause", "BSD-3-Clause AND 0BSD AND Zlib"],
)
def test_permissive_licences_pass(expression):
    assert check_licenses.permitted(expression)


@pytest.mark.parametrize(
    "expression",
    ["UNKNOWN", "GPL-3.0-only", "AGPL-3.0", "LGPL-2.1-or-later", "CC-BY-NC-4.0", "SSPL-1.0",
     "MIT AND GPL-2.0", "Freeware"],
)  # fmt: skip
def test_copyleft_unknown_and_unlisted_licences_fail(expression):
    assert not check_licenses.permitted(expression)


def test_flywire_files_and_vendored_vizdoom_are_refused():
    pattern = check_licenses.FLYWIRE_OR_VENDORED
    for bad in ("data/wiring.feather", "x/connectome_v2.csv", "vendor/lib.py", "src/vizdoom/a.py"):
        assert pattern.search(bad), bad
    assert not pattern.search("src/symbiont/act1/vizdoom_client.py")


def test_waivers_must_name_owner_reason_and_a_short_expiry():
    soon = (TODAY + timedelta(days=10)).isoformat()
    far = (TODAY + timedelta(days=90)).isoformat()
    gone = (TODAY - timedelta(days=1)).isoformat()
    text = f"# c\nCVE-1 jason {soon} dev tool only\nCVE-2 jason {far} too long\n"
    text += f"CVE-3 jason {gone} stale\nCVE-4 jason\n"
    active, problems = check_audit.parse_waivers(text, TODAY)
    assert active == {"CVE-1"}
    assert len(problems) == 3


def _gate(root: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    """Run a gate script with the outer run's base ref and stage removed: they name another repo."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("SYMBIONT_GATE_BASE", "SYMBIONT_GATE_STAGE")
    }
    return subprocess.run(
        ["bash", str(root / "scripts/gates" / script), *args],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip


def _tiny_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src/symbiont").mkdir(parents=True)
    shutil.copytree(GATES, root / "scripts/gates", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(REPO / "pyproject.toml", root / "pyproject.toml")
    (root / ".venv").symlink_to(REPO / ".venv")
    for args in (["init", "-q", "-b", "main"], ["add", "-f", "."]):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    commit = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*commit, "commit", "-q", "-m", "base"], check=True)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "work"], check=True)
    return root


@pytest.mark.periphery
def test_an_undocumented_public_api_turns_the_docstring_gate_red(tmp_path):
    root = _tiny_repo(tmp_path)
    (root / "src/symbiont/bare.py").write_text(
        "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    )
    (root / "src/symbiont/ok.py").write_text('def a():\n    """Why a exists."""\n    return 1\n')
    gate = "check_docstrings.sh"
    red = _gate(root, Path(gate).name, "src/symbiont/bare.py")
    green = _gate(root, Path(gate).name, "src/symbiont/ok.py")
    assert red.returncode != 0, red.stdout
    assert green.returncode == 0, green.stdout + green.stderr


def _coverage_xml(path: Path, filename: str, hits: int) -> None:
    path.write_text(
        '<?xml version="1.0" ?><coverage><sources><source>.</source></sources><packages>'
        f'<package name="p"><classes><class filename="{filename}" name="c"><lines>'
        + "".join(f'<line number="{n}" hits="{hits}"/>' for n in range(1, 4))
        + "</lines></class></classes></package></packages></coverage>"
    )


@pytest.mark.periphery
def test_changed_lines_without_coverage_turn_diff_cover_red(tmp_path):
    root = _tiny_repo(tmp_path)
    (root / "src/symbiont/new.py").write_text("x = 1\ny = 2\nz = 3\n")
    subprocess.run(
        ["git", "-C", str(root), "add", "src/symbiont/new.py"], check=True
    )  # untracked is invisible to diff-cover
    report = root / "cov.xml"
    gate = "diff_coverage.sh"
    _coverage_xml(report, "src/symbiont/new.py", hits=0)
    red = _gate(root, Path(gate).name, str(report))
    _coverage_xml(report, "src/symbiont/new.py", hits=1)
    green = _gate(root, Path(gate).name, str(report))
    assert red.returncode == 1, red.stdout + red.stderr
    assert green.returncode == 0, green.stdout + green.stderr


@pytest.mark.periphery
def test_a_missing_coverage_report_cannot_judge(tmp_path):
    root = _tiny_repo(tmp_path)
    gate = "diff_coverage.sh"
    out = _gate(root, Path(gate).name, str(root / "none.xml"))
    assert out.returncode == 2
