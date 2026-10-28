"""QG-SAST-01 verdict from a semgrep --json report.

ERROR blocks (exit 1), WARNING is advisory, INFO is ignored; scan errors exit 2.
Usage: check_registry_findings.py REPORT.json
"""

import json
import sys
from collections import Counter
from pathlib import Path

EXIT_FINDINGS = 1
EXIT_CANNOT_JUDGE = 2


class ReportError(RuntimeError):
    """The semgrep report is missing, unreadable or records scan errors."""


def load_report(path: Path) -> dict:
    """Read the report; raise ReportError rather than treat a bad report as clean."""
    if not path.is_file():
        raise ReportError(f"no semgrep report at {path}: the scan did not run")
    try:
        report = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise ReportError(f"{path} is not valid JSON: {err}") from err
    errors = report.get("errors", [])
    if errors:
        first = errors[0].get("message", errors[0])
        raise ReportError(f"semgrep reported {len(errors)} scan error(s); first: {first}")
    return report


def by_severity(report: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for hit in report.get("results", []):
        grouped.setdefault(hit["extra"]["severity"], []).append(hit)
    return grouped


def describe(hit: dict) -> str:
    rule = hit["check_id"].rsplit(".", 1)[-1]
    return f"{hit['path']}:{hit['start']['line']}: {rule}"


def summary(grouped: dict[str, list[dict]]) -> str:
    counts = Counter({sev: len(hits) for sev, hits in grouped.items()})
    return (
        f"QG-SAST-01: {counts['ERROR']} error (blocking), "
        f"{counts['WARNING']} warning (advisory), {counts['INFO']} info (ignored)"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return EXIT_CANNOT_JUDGE
    try:
        grouped = by_severity(load_report(Path(argv[1])))
    except ReportError as err:
        print(f"QG-SAST-01 cannot judge: {err}", file=sys.stderr)
        return EXIT_CANNOT_JUDGE
    for hit in grouped.get("ERROR", []):
        print(f"ERROR   {describe(hit)}")
    for hit in grouped.get("WARNING", []):
        print(f"warning {describe(hit)}")
    print(summary(grouped))
    return EXIT_FINDINGS if grouped.get("ERROR") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
