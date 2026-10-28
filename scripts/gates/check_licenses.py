"""QG-DEP-02 license allowlist for what ships. Prevents Forensic Coding: the license story told
to users must match the lockfile, and a copyleft or unknown license arriving as a transitive
dependency is otherwise found by a lawyer, not a gate.

Judged on the runtime closure of uv.lock (`uv export --no-dev`), read from the installed
packages by pip-licenses. A runtime package whose license is not on the allowlist, is UNKNOWN,
carries an NC or ND clause, or is GPL/AGPL/SSPL blocks. Dev-group packages are listed as
advisory: they never link into what ships. Also blocks a tracked FlyWire file (*.feather,
*connectome*) or a vendored ViZDoom (a `vizdoom` path component or anything under vendor/).

An expression joined by OR passes when any alternative is allowed; AND needs every part.
Allowlist = the standard's (MIT, BSD-2/3, Apache-2.0, ISC, PSF, MPL-2.0, Unlicense, CC0) plus the
permissive 0BSD, MIT-0 and Zlib that numpy's bundled-code license expression names.

Exit 0 clean, 1 findings, 2 the gate could not run (no pip-licenses, no lockfile export).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = (
    "mit", "mit license", "mit-0", "bsd", "bsd license", "bsd-2-clause", "bsd-3-clause",
    "3-clause bsd license", "2-clause bsd license", "0bsd", "zlib", "apache-2.0",
    "apache software license", "apache license 2.0", "isc", "isc license (iscl)", "psf-2.0",
    "python software foundation license", "mpl-2.0", "mozilla public license 2.0 (mpl 2.0)",
    "unlicense", "the unlicense (unlicense)", "cc0-1.0",
)  # fmt: skip
FORBIDDEN = re.compile(r"(?<![l])gpl|agpl|sspl|non-?commercial|-nc\b|-nd\b|unknown", re.I)
FLYWIRE_OR_VENDORED = re.compile(r"\.feather$|connectome|(^|/)vendor/|(^|/)vizdoom(/|\.py$)", re.I)


class GateError(RuntimeError):
    """The gate cannot judge (tool missing, lockfile export failed)."""


def permitted(expression: str) -> bool:
    """True when the license expression is wholly acceptable."""
    text = expression.strip().strip("()").strip()
    if FORBIDDEN.search(text):
        return False
    if " OR " in text:
        return any(permitted(part) for part in text.split(" OR "))
    if " AND " in text:
        return all(permitted(part) for part in text.split(" AND "))
    return text.lower() in ALLOWED


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def run(*args: str) -> str:
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise GateError(f"{' '.join(args[:3])} failed: {out.stderr.strip()[-300:]}")
    return out.stdout


def runtime_packages() -> set[str]:
    text = run("uv", "export", "--frozen", "--no-hashes", "--no-emit-project", "--no-dev")
    names = {canonical(m.group(1)) for m in re.finditer(r"^([A-Za-z0-9._-]+)==", text, re.M)}
    if not names:
        raise GateError("the runtime closure of uv.lock is empty: nothing would be checked")
    return names


def installed_licences() -> dict[str, str]:
    text = run("uv", "run", "--no-sync", "pip-licenses", "--format=json", "--from=mixed")
    return {canonical(row["Name"]): row["License"] for row in json.loads(text)}


def forbidden_paths() -> list[str]:
    tracked = run("git", "ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    return [f for f in tracked if FLYWIRE_OR_VENDORED.search(f)]


def main() -> int:
    try:
        shipped, licenses = runtime_packages(), installed_licences()
        paths = forbidden_paths()
    except GateError as err:
        print(f"QG-DEP-02 cannot judge: {err}", file=sys.stderr)
        return 2
    missing = sorted(shipped - licenses.keys())
    problems = [f"runtime package {n} is not installed, so its license is unread" for n in missing]
    problems += [
        f"runtime package {n}: license {licenses[n]!r} is not on the allowlist"
        for n in sorted(shipped & licenses.keys())
        if not permitted(licenses[n])
    ]
    problems += [f"tracked FlyWire or vendored ViZDoom path: {p}" for p in paths]
    advisory = sorted(n for n, lic in licenses.items() if n not in shipped and not permitted(lic))
    for problem in problems:
        print(f"QG-DEP-02: {problem}")
    print(
        f"QG-DEP-02: {'FAIL' if problems else 'OK'} ({len(shipped)} runtime packages; "
        f"{len(advisory)} dev-only off the allowlist, advisory)"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
