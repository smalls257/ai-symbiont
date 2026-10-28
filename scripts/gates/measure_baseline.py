"""Measure how far the whole tree is from the gates, and write scripts/gates/baseline.json.

Phase 1 holds only changed files to the full bar; this records what the unchanged rest
would fail today, so phase 2 has a number to drive to zero and a ratchet to hold it
(Paper Tiger prevention: a cleanup without a baseline cannot show it cleaned anything).

Usage: measure_baseline.py [--write]      (default: print only)
"""

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import baseline_wired  # noqa: E402
import check_claims  # noqa: E402
import check_file_length  # noqa: E402
import check_naming  # noqa: E402
import check_nesting  # noqa: E402

CORE = (
    "src/symbiont/core/",
    "src/symbiont/miner/",
    "src/symbiont/records/",
    "src/symbiont/routeb/",
)


def _baseline_commit() -> str:
    """The commit the baseline describes: the fork point from main, so files added to main
    since (and not yet merged here) are not counted against this tree."""
    main = os.environ.get("SYMBIONT_GATE_BASE", "main")
    out = subprocess.run(
        ["git", "merge-base", main, "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


BASE = _baseline_commit()
SKIP = ("tests/fixtures/", "spikes/", ".claude/", ".venv/")


def tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--no-sync", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def tracked(suffix: str) -> list[str]:
    """Files on the base branch: the baseline measures what main already carries."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", BASE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [f for f in out if f.endswith(suffix) and not f.startswith(SKIP)]


def ruff_counts(files: list[str]) -> dict:
    found = json.loads(tool("ruff", "check", "--output-format", "json", *files).stdout or "[]")
    by_rule = Counter(item["code"] for item in found)
    unformatted = tool("ruff", "format", "--check", *files).stdout.count(
        "File would be reformatted"
    )
    return {
        "check_findings": len(found),
        "by_rule": dict(by_rule.most_common()),
        "files_needing_format": unformatted,
    }


def lizard_offenders(files: list[str], ccn: int, nloc: int, params: int) -> int:
    if not files:
        return 0
    wl = str(ROOT / ".lizard-whitelist.txt")
    flags = ["-C", str(ccn), "-T", f"nloc={nloc}", "-a", str(params), "-W", wl, "-w"]
    return tool("lizard", *files, *flags).stdout.count(": warning:")


def naming_counts(files: list[str]) -> dict:
    """Findings by rule over src, scripts and ops (tests are not named-checked)."""
    scope = [f for f in files if f.startswith(("src/", "scripts/", "ops/"))]
    errors = []
    for f in scope:
        errors += check_naming.check_source((ROOT / f).read_text(), f, set())[0]
    return {
        "vague_name": sum("vague word" in e for e in errors),
        "single_letter_name": sum("single-letter" in e for e in errors),
        "two_or_more_bool_params": sum("bool parameters" in e for e in errors),
    }


def size_counts(sized: list[str]) -> dict:
    classes = sum(
        len(check_file_length.oversized_classes(f, (ROOT / f).read_text(), set())) for f in sized
    )
    long_files = [
        f for f in sized if check_file_length.too_long(f, (ROOT / f).read_text(), set()) is not None
    ]
    return {
        "classes_over_200_lines_or_12_public_methods": classes,
        "files_over_400_src_or_600_test_lines": len(long_files),
    }


def structure_counts(files: list[str]) -> dict:
    src = [f for f in files if f.startswith(("src/symbiont/", "scripts/", "ops/"))]
    pure = [f for f in src if f.startswith(CORE)]
    edge = [f for f in src if f not in pure]
    tests = [f for f in files if f.startswith("tests/")]
    nesting = sum(len(check_nesting.offenders((ROOT / f).read_text(), f, set())) for f in src)
    return {
        "lizard_pure_core_over_10ccn_30nloc": lizard_offenders(pure, 10, 30, 5),
        "lizard_rest_of_src_scripts_ops_over_12ccn_40nloc": lizard_offenders(edge, 12, 40, 5),
        "lizard_test_functions_over_60nloc": lizard_offenders(tests, 30, 60, 12),
        "nesting_functions_over_3": nesting,
        **size_counts(src + tests),
        "naming": naming_counts(files),
    }


def semgrep_counts(files: list[str]) -> dict:
    scan = [f for f in files if f.startswith(("src/", "scripts/", "ops/"))]
    out = tool(
        "semgrep",
        "scan",
        "--metrics=off",
        "--disable-version-check",
        "--quiet",
        "--json",
        "--config",
        ".semgrep/symbiont",
        *scan,
    )
    results = json.loads(out.stdout)["results"]
    return dict(Counter(r["check_id"].rsplit(".", 1)[-1] for r in results))


def claims_count() -> int:
    docs = [f for f in tracked(".md") + tracked(".html") if check_claims.in_scope(f)]
    return sum(len(check_claims.problems_in(f, (ROOT / f).read_text())) for f in docs)


def secrets_findings() -> dict:
    """Every commit on the base branch, so deleted-but-published leaks count too."""
    report = HERE / ".baseline-gitleaks.json"
    subprocess.run(
        [
            "gitleaks",
            "git",
            "--log-opts",
            BASE,
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--no-banner",
            "--redact",
            "--report-format",
            "json",
            "--report-path",
            str(report),
            str(ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    found = json.loads(report.read_text() or "[]")
    report.unlink()
    pairs = sorted({(f["RuleID"], f["File"]) for f in found})
    return {
        "unique_rule_file_pairs": len(pairs),
        "by_rule": dict(Counter(rule for rule, _ in pairs)),
        "files": sorted({file for _, file in pairs}),
    }


def mypy_errors() -> int:
    out = tool("mypy")
    return sum(1 for line in out.stdout.splitlines() if ": error:" in line)


def measure() -> dict:
    py = tracked(".py")
    return {
        "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
        "commit": BASE,
        "scope": "whole tree, excluding tests/fixtures, spikes, .claude",
        "ruff": ruff_counts(py),
        **structure_counts(py),
        "semgrep": semgrep_counts(py + tracked(".sh")),
        "semgrep_registry_QG_SAST_01": baseline_wired.registry_counts(tracked("")),
        "docstrings_QG_RD_01": baseline_wired.docstring_coverage(),
        "type_ignores_QG_TYP_03": baseline_wired.type_ignore_count(),
        "dependencies_QG_DEP_01_02": baseline_wired.licence_and_audit_summary(),
        "claims_untagged_or_forbidden": claims_count(),
        "mypy_errors_src": mypy_errors(),
        "secrets_history_of_base": secrets_findings(),
    }


if __name__ == "__main__":
    baseline = measure()
    print(json.dumps(baseline, indent=2))
    if "--write" in sys.argv:
        (HERE / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
