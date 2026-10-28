"""QG-SAST-01: the registry-pack gate. Prevents Silent Fallback: a missing snapshot, a foreign
semgrep version or a report with scan errors must be a failure, never "no findings"."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATES = REPO / "scripts" / "gates"
sys.path.insert(0, str(GATES))

import check_registry_findings as verdict  # noqa: E402


def _hit(severity: str, rule: str = "python.x.rule-name") -> dict:
    return {
        "check_id": rule,
        "path": "src/a.py",
        "start": {"line": 3},
        "extra": {"severity": severity},
    }


def _report(tmp_path: Path, results: list[dict], errors: list[dict] | None = None) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"results": results, "errors": errors or []}))
    return path


def test_an_error_finding_blocks(tmp_path, capsys):
    assert verdict.main(["x", str(_report(tmp_path, [_hit("ERROR")]))]) == verdict.EXIT_FINDINGS
    assert "ERROR   src/a.py:3: rule-name" in capsys.readouterr().out


def test_warnings_are_advisory_and_info_is_ignored(tmp_path, capsys):
    report = _report(tmp_path, [_hit("WARNING"), _hit("INFO"), _hit("INFO")])
    assert verdict.main(["x", str(report)]) == 0
    assert "0 error (blocking), 1 warning (advisory), 2 info (ignored)" in capsys.readouterr().out


def test_scan_errors_mean_the_gate_cannot_judge_not_clean(tmp_path):
    report = _report(tmp_path, [], errors=[{"message": "rule failed to parse"}])
    assert verdict.main(["x", str(report)]) == verdict.EXIT_CANNOT_JUDGE


def test_a_missing_or_garbled_report_cannot_judge(tmp_path):
    assert verdict.main(["x", str(tmp_path / "absent.json")]) == verdict.EXIT_CANNOT_JUDGE
    garbled = tmp_path / "bad.json"
    garbled.write_text("{not json")
    assert verdict.main(["x", str(garbled)]) == verdict.EXIT_CANNOT_JUDGE


@pytest.mark.periphery
def test_a_missing_snapshot_exits_2_naming_the_fetch_script(tmp_path):
    shadow = tmp_path / "repo"
    shutil.copytree(GATES, shadow / "scripts/gates", ignore=shutil.ignore_patterns("__pycache__"))
    (shadow / ".semgrep").mkdir()
    shutil.copy(REPO / ".semgrep/VERSION", shadow / ".semgrep/VERSION")
    (shadow / ".venv").symlink_to(REPO / ".venv")
    subprocess.run(["git", "init", "-q", str(shadow)], check=True)
    out = subprocess.run(
        ["bash", str(shadow / "scripts/gates/semgrep_registry.sh"), "--tree"],
        cwd=shadow, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert out.returncode == 2
    assert "fetch_semgrep_packs.sh" in out.stderr
