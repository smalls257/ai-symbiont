"""Which files reference which, from a static scan of a Python repo checkout.

Feeds the blast-radius signal: `references[path]` = repo files that import
`path`, or, for test files, name it by convention (`tests/x/test_duckdb.py`
tests `duckdb.py`; sqlglot's dialect tests pick their dialect by string, so
imports alone would miss them). Nothing is executed; files are only parsed.
A file that does not parse raises, naming the file: a silently skipped file
would hide every reference it makes.
"""

import ast
from collections import defaultdict
from pathlib import Path

_SKIP_DIRS = {"node_modules", "build", "dist", "__pycache__", "venv"}


def build_references(repo_root: Path) -> dict[str, frozenset[str]]:
    """Map each repo file to the files that import it, plus its conventionally named tests."""
    files = _python_files(repo_root)
    modules = {_module_name(f): f for f in files}
    refs: dict[str, set[str]] = defaultdict(set)
    for path in files:
        source = (repo_root / path).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=path)
        for target in _imported_files(tree, path, modules):
            if target != path:
                refs[target].add(path)
    for test_file, subject in _tests_by_convention(files):
        refs[subject].add(test_file)
    return {path: frozenset(found) for path, found in refs.items()}


def _python_files(root: Path) -> list[str]:
    found = []
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if any(p.startswith(".") or p in _SKIP_DIRS for p in parts[:-1]):
            continue
        found.append("/".join(parts))
    return found


def _module_name(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported_files(tree: ast.AST, path: str, modules: dict[str, str]) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = [[a.name] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_module(node, path)
            # `from pkg import name`: name may be a submodule, else it lives in pkg.
            candidates = [[f"{base}.{a.name}" if base else a.name, base] for a in node.names]
        else:
            continue
        for options in candidates:
            if hit := next((modules[m] for m in options if m in modules), None):
                found.add(hit)
    return found


def _absolute_module(node: ast.ImportFrom, path: str) -> str:
    if node.level == 0:
        return node.module or ""
    package = _module_name(path).split(".")
    if not path.endswith("__init__.py"):
        package = package[:-1]
    package = package[: len(package) - (node.level - 1)]
    return ".".join([*package, *([node.module] if node.module else [])])


def _tests_by_convention(files: list[str]) -> list[tuple[str, str]]:
    by_stem: dict[str, list[str]] = defaultdict(list)
    for path in files:
        name = path.rsplit("/", 1)[-1]
        if not name.startswith("test_"):
            by_stem[name].append(path)
    pairs = []
    for path in files:
        name = path.rsplit("/", 1)[-1]
        if name.startswith("test_"):
            pairs += [(path, subject) for subject in by_stem.get(name.removeprefix("test_"), [])]
    return pairs
