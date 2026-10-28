"""Whole-tree counts for the gates wired after phase 1, folded into baseline.json.

A tool that cannot run raises: a baseline of zeros from a broken scan would hide the debt.
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


def frontend_counts() -> dict:
    """QG-FE-01/02/03 over the whole dashboard and docs: what a touch would have to fix."""
    dash = ROOT / "dashboard"
    lint = subprocess.run(
        ["npx", "--no-install", "eslint", "--format", "json", "."],
        cwd=dash, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if not lint.stdout.startswith("["):
        raise RuntimeError(
            f"eslint gave no report (run: cd dashboard && npm ci): {lint.stderr[-300:]}"
        )
    cdn = run_tool("python", str(ROOT / "scripts/gates/check_cdn.py"))
    html = run_tool("bash", str(ROOT / "scripts/gates/check_html.sh"), *html_files())
    if cdn.returncode == 2 or html.returncode == 2:
        raise RuntimeError(f"frontend gate could not run: {cdn.stderr[-200:]}{html.stderr[-200:]}")
    return {
        "eslint_errors_dashboard": sum(f["errorCount"] for f in json.loads(lint.stdout)),
        "external_loads": sum(line.startswith("QG-FE-02: ") and "external load" in line
                              for line in cdn.stdout.splitlines()),
        "html_validity_errors": next(
            (int(m.group(1)) for m in re.finditer(r"QG-FE-03: (\d+) error", html.stdout)), 0
        ),
    }  # fmt: skip


def html_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "dashboard", "docs"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return [f for f in out.stdout.splitlines() if f.endswith(".html") and (ROOT / f).is_file()]


def comment_findings(files: list[str]) -> dict:
    """QG-RD-04 over src, scripts and ops: findings the advisory gate would print."""
    scope = [f for f in present(files) if f.startswith(("src/", "scripts/", "ops/"))]
    out = run_tool("python", str(ROOT / "scripts/gates/check_comments.py"), *scope)
    if out.returncode == 2:
        raise RuntimeError(f"check_comments.py could not run: {out.stderr[-300:]}")
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("QG-RD-04: ")]
    rules = {
        "framework_vocabulary": "framework term",
        "docstring_over_cap": "docstring over",
        "comment_block_over_3": "comment block over",
        "todo_without_owner_date": "TODO/FIXME",
        "restates_next_line_or_signature": "restate",
    }
    counts = {key: sum(needle in ln for ln in lines) for key, needle in rules.items()}
    return {**counts, "findings": sum("finding(s)" not in ln for ln in lines)}


def mutation_score_if_measured() -> dict:
    """QG-TST-05: the last scripts/gates/mutation.sh result, if mutants/ holds one. The run is
    minutes long, so the baseline reads it instead of starting it; None means never measured."""
    stats = ROOT / "mutants" / "mutmut-cicd-stats.json"
    if not stats.is_file():
        return {"killed_percent": None, "note": "not measured: run scripts/gates/mutation.sh"}
    data = json.loads(stats.read_text())
    share = 100.0 * (data["killed"] + data["timeout"]) / data["total"]
    return {
        "killed_percent": round(share, 1),
        "mutants": data["total"],
        "survived": data["survived"],
    }
