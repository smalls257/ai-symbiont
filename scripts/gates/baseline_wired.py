"""Whole-tree counts for the gates wired after phase 1 (the ones documented but once unrun).

Split from measure_baseline.py so each file stays under its size cap. Each function returns a
plain dict of counts; measure_baseline.py folds them into baseline.json. A tool that cannot run
raises: a baseline of zeros from a broken scan would let phase 2 "clean" nothing (Paper Tiger).
"""

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_type_ignores  # noqa: E402

SKIP = ("tests/fixtures/", "spikes/", ".claude/", ".venv/", "uv.lock")


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--no-sync", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def present(files: list[str]) -> list[str]:
    """Files of the base tree that exist in this checkout and are in scope for a scan."""
    return [f for f in files if not f.startswith(SKIP) and (ROOT / f).is_file()]


def registry_counts(files: list[str]) -> dict:
    """QG-SAST-01 over the whole tree: findings by severity, plus the blocking ones by name."""
    report = ROOT / ".baseline-registry.json"
    out = run_tool(
        "semgrep", "scan", "--metrics=off", "--disable-version-check", "--quiet", "--json",
        "--output", str(report), "--config", ".semgrep/registry", *present(files),
    )  # fmt: skip
    if not report.is_file():
        raise RuntimeError(f"registry scan produced no report: {out.stderr[-300:]}")
    found = json.loads(report.read_text())
    report.unlink()
    if found.get("errors"):
        raise RuntimeError(f"registry scan errors: {found['errors'][0]}")
    hits = found["results"]
    return {
        "by_severity": dict(Counter(h["extra"]["severity"] for h in hits)),
        "error_findings": sorted(
            f"{h['path']}:{h['check_id'].rsplit('.', 1)[-1]}"
            for h in hits
            if h["extra"]["severity"] == "ERROR"
        ),
    }


def docstring_coverage(src: str = "src/symbiont") -> dict:
    """QG-RD-01 whole-tree figure: interrogate's own percentage over the public API."""
    out = run_tool("interrogate", "--fail-under", "0", src)
    match = re.search(r"actual: ([0-9.]+)%", out.stdout)
    if match is None:
        raise RuntimeError(
            f"interrogate gave no percentage: {out.stdout[-300:]}{out.stderr[-300:]}"
        )
    return {"public_api_documented_percent": float(match.group(1)), "bar_percent": 90}


def type_ignore_count() -> dict:
    """QG-TYP-03 tree-wide count against its ceiling."""
    total, bad = check_type_ignores.audit(check_type_ignores.tracked_python())
    return {"type_ignore_comments": total, "malformed": len(bad)}


def licence_and_audit_summary() -> dict:
    """QG-DEP-01/02 as the scripts print them; the baseline records the verdict lines."""
    lines = {}
    for key, script in (("QG-DEP-01", "check_audit.py"), ("QG-DEP-02", "check_licenses.py")):
        out = run_tool("python", str(ROOT / "scripts/gates" / script))
        if out.returncode == 2:
            raise RuntimeError(f"{script} could not run: {out.stderr[-300:]}")
        verdict = [line for line in out.stdout.splitlines() if line.startswith(f"{key}: ")]
        lines[key] = verdict[-1].removeprefix(f"{key}: ")
    return lines
