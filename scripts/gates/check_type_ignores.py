"""QG-TYP-03: every type: ignore names [error-code] # reason, and the count stays under the ceiling.

The ceiling is type-ignore-ceiling.txt; raising it is a gate change. Exit 2 if it cannot run.
Usage: check_type_ignores.py [FILE ...]   default: every tracked Python file in scope
"""

import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CEILING_FILE = Path(__file__).with_name("type-ignore-ceiling.txt")
SCOPE = ("src/", "scripts/", "ops/", "tests/")
EXCLUDED = ("tests/fixtures/", "spikes/")
IGNORE = re.compile(r"#\s*type:\s*ignore(?P<rest>.*)")
WELL_FORMED = re.compile(r"^\[[a-z][a-z-]*(?:,\s*[a-z][a-z-]*)*\]\s*#\s*\S.*$")


class GateError(RuntimeError):
    """The gate cannot judge (no ceiling, unreadable file)."""


def read_ceiling() -> int:
    path = CEILING_FILE
    if not path.is_file():
        raise GateError(f"no ceiling file at {path}: a ratchet without a number checks nothing")
    text = path.read_text().strip()
    if not text.isdigit():
        raise GateError(f"{path} must hold one non-negative integer, found {text!r}")
    return int(text)


def ignores_in(source: str, name: str) -> list[tuple[int, str]]:
    """(line, comment text after the marker) for every real comment; strings are skipped."""
    found = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            match = token.type == tokenize.COMMENT and IGNORE.search(token.string)
            if match:
                found.append((token.start[0], match.group("rest").strip()))
    except (tokenize.TokenError, IndentationError) as err:
        raise GateError(f"{name}: cannot tokenize: {err}") from err
    return found


def tracked_python() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if out.returncode != 0:
        raise GateError(f"git ls-files failed: {out.stderr.strip()}")
    return [
        f for f in out.stdout.splitlines() if f.startswith(SCOPE) and not f.startswith(EXCLUDED)
    ]


def audit_source(source: str, name: str) -> tuple[int, list[str]]:
    """Ignores in one file and one message per malformed one."""
    found = ignores_in(source, name)
    problems = [
        f"{name}:{line}: type: ignore needs [error-code] # reason"
        for line, rest in found
        if not WELL_FORMED.match(rest)
    ]
    return len(found), problems


def audit(files: list[str]) -> tuple[int, list[str]]:
    """Total ignores and the malformed ones across the files that exist."""
    total, problems = 0, []
    for name in files:
        path = ROOT / name
        if path.is_file():
            count, bad = audit_source(path.read_text(), name)
            total, problems = total + count, problems + bad
    return total, problems


def main(argv: list[str]) -> int:
    try:
        ceiling = read_ceiling()
        total, problems = audit(argv[1:] or tracked_python())
    except GateError as err:
        print(f"QG-TYP-03 cannot judge: {err}", file=sys.stderr)
        return 2
    if total > ceiling and not argv[1:]:
        problems.append(f"{total} type: ignore comments exceed the ceiling of {ceiling}")
    for problem in problems:
        print(f"QG-TYP-03: {problem}")
    if not problems:
        print(f"QG-TYP-03: OK ({total} of at most {ceiling} type: ignore comments)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
