"""Whole-tree counts for the gates wired after phase 1 (the ones documented but once unrun).

Split from measure_baseline.py so each file stays under its size cap. Each function returns a
plain dict of counts; measure_baseline.py folds them into baseline.json. A tool that cannot run
raises: a baseline of zeros from a broken scan would let phase 2 "clean" nothing (Paper Tiger).
"""

import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
