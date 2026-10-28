"""QG-DEP-01: pip-audit over the exported lockfile (network; full only).

Any runtime finding blocks; dev-group findings are advisory. Waivers: audit_waivers.txt.
Exit 0 clean, 1 findings or bad waivers, 2 cannot run.
"""

import json
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAIVERS = Path(__file__).with_name("audit_waivers.txt")
MAX_WAIVER_DAYS = 30
GROUPS = {"runtime": ["--no-dev"], "dev": ["--only-dev"]}


class AuditError(RuntimeError):
    """The audit could not run, so it cannot call the tree clean."""


def parse_waivers(text: str, today: date) -> tuple[set[str], list[str]]:
    """Active advisory ids and one message per bad line."""
    active, problems = set(), []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split(None, 3)
        problem = waiver_problem(parts, today)
        if problem:
            problems.append(f"audit_waivers.txt:{number}: {problem}")
        else:
            active.add(parts[0])
    return active, problems


def waiver_problem(parts: list[str], today: date) -> str | None:
    if len(parts) < 4:
        return "needs: <advisory-id> <owner> <expiry> <reason>"
    try:
        expiry = date.fromisoformat(parts[2])
    except ValueError:
        return f"expiry {parts[2]!r} is not YYYY-MM-DD"
    if expiry < today:
        return f"waiver for {parts[0]} expired on {expiry}"
    if expiry > today + timedelta(days=MAX_WAIVER_DAYS):
        return f"waiver for {parts[0]} runs past {MAX_WAIVER_DAYS} days"
    return None


def exported_requirements(flags: list[str], target: Path) -> None:
    out = subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", *flags],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if out.returncode != 0:
        raise AuditError(f"uv export failed: {out.stderr.strip()[-300:]}")
    target.write_text(out.stdout)


def audit_group(name: str, flags: list[str], work: Path) -> list[tuple[str, str, str]]:
    """(package, version, advisory id) for every vulnerability pip-audit reports."""
    requirements = work / f"{name}.txt"
    exported_requirements(flags, requirements)
    out = subprocess.run(
        ["uv", "run", "--no-sync", "pip-audit", "-r", str(requirements), "--no-deps",
         "--disable-pip", "--progress-spinner", "off", "--format", "json"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    try:
        report = json.loads(out.stdout)
    except json.JSONDecodeError as err:
        raise AuditError(
            f"pip-audit gave no report for {name}: {out.stderr.strip()[-300:]}"
        ) from err
    return [
        (dep["name"], dep["version"], vuln["id"])
        for dep in report["dependencies"]
        for vuln in dep.get("vulns", [])
    ]


def main() -> int:
    waivers = WAIVERS.read_text() if WAIVERS.is_file() else ""
    active, problems = parse_waivers(waivers, date.today())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            found = {g: audit_group(g, flags, Path(tmp)) for g, flags in GROUPS.items()}
    except AuditError as err:
        print(f"QG-DEP-01 cannot audit: {err}", file=sys.stderr)
        return 2
    for group, hits in found.items():
        for package, version, advisory in hits:
            if advisory in active:
                continue
            if group == "runtime":
                problems.append(f"{group}: {package} {version} has {advisory}")
            else:
                print(f"QG-DEP-01 advisory: {group}: {package} {version} has {advisory}")
    for problem in problems:
        print(f"QG-DEP-01: {problem}")
    counts = ", ".join(f"{g} {len(h)}" for g, h in found.items())
    print(f"QG-DEP-01: {'FAIL' if problems else 'OK'} (advisories: {counts}; waived {len(active)})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
