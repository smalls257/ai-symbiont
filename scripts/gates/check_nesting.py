"""QG-CPX-01/02 nesting depth. Prevents God Method (Shield): a deeply nested function
hides several jobs behind indentation.

Lizard's nested-structure extension (-ENS) cannot do this job here: on lizard 1.24.3 it
warns on every Python function whatever the limit, because Python blocks are indentation,
not braces. So nesting is measured on the AST. Control structures counted: if, for,
while, try, with, match (and their async forms). Limit: 3 levels everywhere.

Usage: check_nesting.py FILE.py ...   (exit 1 on any function over its limit)
Waivers: the same delete-only .lizard-whitelist.txt, entries `path.py:function`.
"""

import ast
import subprocess
import sys
from pathlib import Path

LIMIT = 3
NESTING_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class GateConfigError(RuntimeError):
    """The gate cannot run: it would silently check nothing."""


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise GateConfigError("not inside a git work tree")
    return Path(out.stdout.strip())


def read_whitelist(path: Path) -> set[str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise GateConfigError(f"missing or empty whitelist: {path}")
    entries = set()
    for line in path.read_text().splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.add(entry)
    return entries


def _is_elif(parent: ast.AST, child: ast.AST) -> bool:
    """An `elif` is an If alone in its parent's else branch: same level, not one deeper."""
    return isinstance(parent, ast.If) and isinstance(child, ast.If) and parent.orelse == [child]


def max_depth(node: ast.AST, depth: int = 0) -> int:
    """Deepest control-structure nesting below `node`, not descending into inner defs."""
    deepest = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, FUNCTION_NODES + (ast.ClassDef, ast.Lambda)):
            continue
        counts = isinstance(child, NESTING_NODES) and not _is_elif(node, child)
        step = depth + 1 if counts else depth
        deepest = max(deepest, max_depth(child, step))
    return deepest


def offenders(source: str, relpath: str, whitelist: set[str]) -> list[str]:
    limit = LIMIT
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, FUNCTION_NODES):
            continue
        depth = max_depth(node)
        if depth > limit and f"{relpath}:{node.name}" not in whitelist:
            found.append(f"{relpath}:{node.lineno}: {node.name} nests {depth} deep (limit {limit})")
    return found


def main(argv: list[str]) -> int:
    root = repo_root()
    whitelist = read_whitelist(root / ".lizard-whitelist.txt")
    problems = []
    for name in argv:
        path = Path(name).resolve()
        relpath = str(path.relative_to(root))
        problems += offenders(path.read_text(), relpath, whitelist)
    for line in problems:
        print(line, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except GateConfigError as err:
        print(f"gate error: {err}", file=sys.stderr)
        sys.exit(2)
