"""QG-CPX-03 file and class size. Prevents God Class (Shield): a long file or a fat class is
the larval form of a Manager; splitting at 300 lines is cheap, at 1,200 it is a project.

Limits: source files 400 lines (warning above 300), test files 600; a class 200 lines and 12
public methods. Scripts and ops are held to the same caps as src. Waiver: `path.py`
or `path.py:ClassName` entries in the delete-only .lizard-whitelist.txt.

Usage: check_file_length.py FILE.py ...   (exit 1 on any breach; warnings are printed only)
"""

import ast
import subprocess
import sys
from pathlib import Path

SRC_LIMIT, SRC_WARN, TEST_LIMIT = 400, 300, 600
SOURCE_PREFIXES = ("src/symbiont/", "scripts/", "ops/")  # no carve-out for tooling
CLASS_LINES, CLASS_PUBLIC_METHODS = 200, 12


class GateConfigError(RuntimeError):
    """The gate cannot run: it would silently check nothing."""


def limit_for(relpath: str) -> int | None:
    if relpath.startswith(SOURCE_PREFIXES):
        return SRC_LIMIT
    return TEST_LIMIT if relpath.startswith("tests/") else None


def read_whitelist(path: Path) -> set[str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise GateConfigError(f"missing or empty whitelist: {path}")
    lines = (line.split("#", 1)[0].strip() for line in path.read_text().splitlines())
    return {entry for entry in lines if entry}


def too_long(relpath: str, text: str, whitelist: set[str]) -> str | None:
    limit = limit_for(relpath)
    count = len(text.splitlines())
    if limit is None or count <= limit or relpath in whitelist:
        return None
    return f"{relpath}: {count} lines (limit {limit}): God Class; split by responsibility"


def long_but_allowed(relpath: str, text: str) -> str | None:
    count = len(text.splitlines())
    if relpath.startswith(SOURCE_PREFIXES) and SRC_WARN < count <= SRC_LIMIT:
        return f"{relpath}: {count} lines (warning above {SRC_WARN}, limit {SRC_LIMIT})"
    return None


def oversized_classes(relpath: str, text: str, whitelist: set[str]) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.ClassDef) or f"{relpath}:{node.name}" in whitelist:
            continue
        lines = (node.end_lineno or node.lineno) - node.lineno + 1
        methods = [
            m.name
            for m in node.body
            if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef) and not m.name.startswith("_")
        ]
        if lines > CLASS_LINES or len(methods) > CLASS_PUBLIC_METHODS:
            found.append(
                f"{relpath}:{node.lineno}: class {node.name} has {lines} lines, {len(methods)} "
                f"public methods (limits {CLASS_LINES} / {CLASS_PUBLIC_METHODS}): God Class"
            )
    return found


def main(argv: list[str]) -> int:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise GateConfigError("not inside a git work tree")
    root = Path(out.stdout.strip())
    whitelist = read_whitelist(root / ".lizard-whitelist.txt")
    problems = []
    for name in argv:
        path = Path(name).resolve()
        relpath = str(path.relative_to(root))
        text = path.read_text()
        if warning := long_but_allowed(relpath, text):
            print(f"warn  {warning}", file=sys.stderr)
        if problem := too_long(relpath, text, whitelist):
            problems.append(problem)
        problems += oversized_classes(relpath, text, whitelist)
    for line in problems:
        print(line, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except GateConfigError as err:
        print(f"gate error: {err}", file=sys.stderr)
        sys.exit(2)
