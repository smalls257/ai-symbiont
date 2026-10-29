"""Where inside a sqlglot file a patch lands: `DuckDB.Generator.TRANSFORMS`, `Parser._parse_types`.

Glimmer opens the right file early and still never edits (capability-pairs.md: 14 of 14 failed
runs opened the fix file by step 17), so a lesson that names only the module tells it nothing new.
This names the class, method or class-level mapping that encloses every changed line, resolved
against the file as it was before the patch. Pure: diff text and source text in, names out.
"""

import ast
import re
from dataclasses import dataclass

HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")
FILE = re.compile(r"^diff --git a/(\S+) b/")
MODULE_LEVEL = "module level"


@dataclass(frozen=True)
class Place:
    """One enclosing construct in one source file."""

    file: str
    name: str

    def prose(self) -> str:
        """`Name` in `file`, as a lesson says it."""
        return f"`{self.name}` in `{self.file}`"


def _is_change(line: str) -> bool:
    return line[:1] in ("+", "-") and not line.startswith(("+++", "---"))


def changed_lines(diff: str) -> list[str]:
    """Added and removed code lines of a unified diff, without the +/- mark or file headers."""
    return [line[1:] for line in diff.splitlines() if _is_change(line)]


class _Runs:
    """Walks a diff and records, per run of changed lines, the old line before it and its indent."""

    def __init__(self) -> None:
        self.found: dict[str, list[tuple[int, int]]] = {}
        self.path: str | None = None
        self.old = 0
        self.start: int | None = None
        self.indent = 10**6

    def close(self) -> None:
        if self.path and self.start is not None:
            self.found.setdefault(self.path, []).append((self.start, self.indent))
        self.start, self.indent = None, 10**6

    def changed(self, line: str) -> None:
        self.start = self.old - 1 if self.start is None else self.start
        if line[1:].strip():
            self.indent = min(self.indent, len(line[1:]) - len(line[1:].lstrip()))
        self.old += line[0] == "-"

    def read(self, line: str) -> None:
        header, hunk = FILE.match(line), HUNK.match(line)
        if header or hunk:
            self.close()
            self.path = header.group(1) if header else self.path
            self.old = int(hunk.group(1)) if hunk else self.old
        elif self.path and _is_change(line):
            self.changed(line)
        elif self.path and line[:1] in ("", " "):  # a blank context line may lose its space
            self.close()
            self.old += 1


def anchors(diff: str) -> dict[str, list[tuple[int, int]]]:
    """Per file, (old line just before, smallest indent) of each run of changed lines."""
    runs = _Runs()
    for line in diff.splitlines():
        runs.read(line)
    runs.close()
    return runs.found


def _named(node: ast.AST) -> str | None:
    if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        return target.id if isinstance(target, ast.Name) else None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


Span = tuple[int, int, int, str]  # first line, last line, header indent, dotted name


def spans(source: str) -> list[Span]:
    """Every class, function and named assignment, with its lines, indent and dotted name."""
    found: list[Span] = []
    pending: list[tuple[ast.AST, str]] = [(ast.parse(source), "")]
    while pending:
        node, prefix = pending.pop()
        for child in ast.iter_child_nodes(node):
            name = _named(child)
            if name is None:
                pending.append((child, prefix))
                continue
            dotted = f"{prefix}.{name}" if prefix else name
            end = child.end_lineno or child.lineno
            found.append((child.lineno, end, child.col_offset, dotted))
            if isinstance(child, ast.ClassDef):
                pending.append((child, dotted))
    return found


def enclosing(found: list[Span], line: int, indent: int) -> str:
    """The deepest construct holding `line` whose header sits left of code indented `indent`."""
    holding = [
        (last - first, name)
        for first, last, column, name in found
        if first <= line <= last and column < indent
    ]
    return min(holding)[1] if holding else MODULE_LEVEL


def places(diff: str, sources: dict[str, str]) -> list[Place]:
    """Enclosing constructs of every changed run, in diff order; `sources` maps path to old text."""
    found: list[Place] = []
    for path, runs in anchors(diff).items():
        if path not in sources or not path.endswith(".py"):
            continue
        named = spans(sources[path])
        for line, indent in runs:
            place = Place(path, enclosing(named, line, indent))
            if place not in found:
                found.append(place)
    return found


def diff_files(diff: str) -> list[str]:
    """Paths a diff touches, in order."""
    return [match.group(1) for match in map(FILE.match, diff.splitlines()) if match]
