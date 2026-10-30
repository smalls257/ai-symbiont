"""QG-RD-02 / QG-RD-03 naming and boolean arity. Pure AST checks, one message per Violation.

* Vague capability words in function, class and module names (handle, process, manage, do,
  run_it, helper, util(s), misc, data, info, stuff, Manager, Helper, Handler, Processor)
  matched as whole snake_case / CamelCase words. Forensic Coding: the reader cannot tell what
  the unit does. Leaky Narrative: a call site that reads `process(data)` says nothing.
* Single-letter names outside loop and comprehension targets, `x` / `y` and `_`.
  Forensic Coding.
* Two or more bool parameters on one function. God Method in larval form, and a Leaky
  Narrative at every call site. Replace with a StrEnum or two named functions.
* Advisory (printed, exit 0): is_ / use_ / enable_ parameters that can be passed positionally.

Waivers: `.naming-waivers.txt`, delete-only, entries `path.py:name  # owner, reason, expires
YYYY-MM-DD`; an entry with no future expiry date is itself an error.

Usage: check_naming.py FILE.py ...   (exit 1 on any finding, 2 if the waiver file is unusable)
"""

import ast
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

VAGUE_WORDS = frozenset(
    (
        "handle",
        "handler",
        "handlers",
        "process",
        "processor",
        "manage",
        "manager",
        "helper",
        "helpers",
        "util",
        "utils",
        "misc",
        "data",
        "info",
        "stuff",
        "do",
    )
)
VAGUE_PHRASES = ("run_it",)
ALLOWED_SINGLE = frozenset({"x", "y", "_"})
FLAG_PREFIXES = ("is_", "use_", "enable_")
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
EXPIRES = re.compile(r"expires\s+(\d{4}-\d{2}-\d{2})")


class WaiverError(RuntimeError):
    """The waiver file is missing, or an entry lacks an owner-readable expiry."""


def words_of(name: str) -> list[str]:
    return [w.lower() for w in WORDS.findall(name.replace("_", " "))]


def vague_in(name: str) -> str | None:
    lowered = name.lower()
    for phrase in VAGUE_PHRASES:
        if phrase in lowered:
            return phrase
    return next((w for w in words_of(name) if w in VAGUE_WORDS), None)


def read_waivers(path: Path, today: date) -> set[str]:
    if not path.is_file():
        raise WaiverError(f"missing waiver file {path}")
    waived = set()
    for line in path.read_text().splitlines():
        entry, _, comment = line.partition("#")
        if not entry.strip():
            continue
        found = EXPIRES.search(comment)
        if not found or date.fromisoformat(found.group(1)) < today:
            raise WaiverError(f"waiver '{entry.strip()}' has no future 'expires YYYY-MM-DD'")
        waived.add(entry.strip())
    return waived


def _is_bool_param(arg: ast.arg, default: ast.expr | None) -> bool:
    annotated = isinstance(arg.annotation, ast.Name) and arg.annotation.id == "bool"
    literal = isinstance(default, ast.Constant) and isinstance(default.value, bool)
    return annotated or literal


def _params_with_defaults(fn: ast.FunctionDef | ast.AsyncFunctionDef):
    spec = fn.args
    positional = spec.posonlyargs + spec.args
    pad = [None] * (len(positional) - len(spec.defaults))
    defaults = pad + list(spec.defaults)
    yield from ((p, d, False) for p, d in zip(positional, defaults, strict=True))
    yield from ((p, d, True) for p, d in zip(spec.kwonlyargs, spec.kw_defaults, strict=True))


def _loop_targets(tree: ast.AST) -> set[int]:
    """ids of Name nodes that are for-loop or comprehension targets."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            ids.update(id(n) for n in ast.walk(node.target))
    return ids


def _bool_findings(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[list[str], list[str]]:
    bools = [p.arg for p, d, _ in _params_with_defaults(fn) if _is_bool_param(p, d)]
    errors = []
    if len(bools) >= 2:
        errors.append(
            f"{fn.lineno}: {fn.name} takes {len(bools)} bool parameters {bools}: God Method / "
            "Leaky Narrative; use a StrEnum or two named functions"
        )
    warnings = [
        f"{fn.lineno}: {fn.name}({p.arg}) flag-like parameter can be passed positionally; "
        "make it keyword-only"
        for p, _, kwonly in _params_with_defaults(fn)
        if p.arg.startswith(FLAG_PREFIXES) and not kwonly
    ]
    return errors, warnings


def _definition_finding(node: ast.AST) -> tuple[str, str] | None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return None
    word = vague_in(node.name)
    if not word:
        return None
    return node.name, (
        f"{node.lineno}: '{node.name}' uses vague word '{word}' (Forensic Coding / Leaky "
        "Narrative): name the capability in domain words"
    )


def _short_name(node: ast.AST, loops: set[int]) -> str | None:
    if isinstance(node, ast.arg):
        return node.arg
    if isinstance(node, ast.ExceptHandler):
        return node.name
    stored = isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    if stored and not node.id.isupper() and id(node) not in loops:
        return node.id
    return None


def _single_letter_finding(node: ast.AST, loops: set[int]) -> tuple[str, str] | None:
    name = _short_name(node, loops)
    if name is None or len(name) != 1 or name in ALLOWED_SINGLE:
        return None
    return name, f"{node.lineno}: single-letter name '{name}' (Forensic Coding)"


def _name_findings(tree: ast.AST) -> list[tuple[str, str]]:
    """(name, message) pairs for vague and single-letter names."""
    loops = _loop_targets(tree)
    pairs = []
    for node in ast.walk(tree):
        pairs += [_definition_finding(node), _single_letter_finding(node, loops)]
    return [pair for pair in pairs if pair]


def check_source(source: str, relpath: str, waived: set[str]) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one file."""
    tree = ast.parse(source)
    errors, warnings = [], []
    stem = Path(relpath).stem
    if stem != "__init__" and (word := vague_in(stem)) and relpath not in waived:
        errors.append(f"module '{stem}' uses vague word '{word}' (Forensic Coding)")
    for name, message in _name_findings(tree):
        if f"{relpath}:{name}" not in waived:
            errors.append(message)
    for node in ast.walk(tree):
        if isinstance(node, FUNCTIONS) and f"{relpath}:{node.name}" not in waived:
            errs, warns = _bool_findings(node)
            errors += errs
            warnings += warns
    return errors, warnings


def main(argv: list[str]) -> int:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if top.returncode != 0:
        print("gate error: not inside a git work tree", file=sys.stderr)
        return 2
    root = Path(top.stdout.strip())
    try:
        waived = read_waivers(root / ".naming-waivers.txt", date.today())
    except WaiverError as err:
        print(f"gate error: {err}", file=sys.stderr)
        return 2
    failed = False
    for name in argv:
        path = Path(name).resolve()
        relpath = str(path.relative_to(root))
        errors, warnings = check_source(path.read_text(), relpath, waived)
        for line in warnings:
            print(f"warn  {relpath}:{line}", file=sys.stderr)
        for line in errors:
            print(f"QG-RD-02 {relpath}:{line}", file=sys.stderr)
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
