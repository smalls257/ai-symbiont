"""QG-RD-04 comment policy. Prevents Fossil Comments: a comment that restates the line below it,
a TODO nobody owns, or a docstring that repeats the signature, carries no why and goes stale.

Findings (Python files in src, scripts and ops):
  * TODO / FIXME without `(owner, YYYY-MM-DD)`: write `TODO(jane, 2026-11-30): why`.
  * a comment whose words are >= 70% the words of the statement below it (what, not why).
    Comments that give a reason (because, so that, otherwise ...) or are tool directives
    (noqa, type:, fmt:, nosemgrep, pragma) are exempt. hypothesis: the overlap threshold
    needs tuning on this tree before it may block; the gate is advisory at C.
  * a one-line docstring whose words are all in the function's name and parameter names.
Commented-out code is ruff ERA001 in QG-LINT-01, not repeated here.

Exit 1 on any finding (run.sh reports it as advisory), 2 if a file cannot be read or parsed.
Usage: check_comments.py FILE ...
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

OVERLAP_LIMIT = 0.7  # QG-RD-04: the standard's number, still [hypothesis] until tuned here
MIN_COMMENT_WORDS = 3
TODO_OK = re.compile(r"\b(?:TODO|FIXME)\(([^,()]+),\s*\d{4}-\d{2}-\d{2}\)")
TODO_ANY = re.compile(r"\b(?:TODO|FIXME)\b")
DIRECTIVE = re.compile(
    r"^#\s*(?:noqa|type:|fmt:|nosemgrep|pragma|pylint|mypy|ruff|shellcheck|!)", re.I
)
REASON = re.compile(
    r"\b(?:because|so that|so a|so the|otherwise|since|why|prevents?|avoids?|instead|unless"
    r"|must|never)\b",
    re.I,
)
FILLER = frozenset(
    {"a", "an", "the", "of", "for", "to", "and", "or", "in", "on", "is", "are", "be", "it"}
    | {"this", "that", "with", "as", "by", "at", "from"}
)
DOC_FILLER = FILLER | {"return", "returns", "get", "gets", "set", "sets", "given", "function"}
DOC_FILLER = DOC_FILLER | {"method", "result"}


class GateError(RuntimeError):
    """A file cannot be read or parsed, so it cannot be judged."""


def words(text: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {w for w in re.findall(r"[a-z][a-z0-9]+", spaced.lower()) if w not in FILLER}


def next_statement(lines: list[str], after: int) -> str:
    """The first non-blank, non-comment line after `after` (0-based), or ''."""
    for line in lines[after + 1 :]:
        text = line.strip()
        if text and not text.startswith("#"):
            return text
    return ""


def comment_problems(source: str, name: str) -> list[str]:
    lines = source.splitlines()
    problems = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        row, text = token.start[0], token.string
        if TODO_ANY.search(text) and not TODO_OK.search(text):
            problems.append(f"{name}:{row}: TODO/FIXME needs (owner, YYYY-MM-DD)")
        elif restates_next_line(token, lines):
            problems.append(f"{name}:{row}: comment restates the next line (say why, not what)")
    return problems


def restates_next_line(token: tokenize.TokenInfo, lines: list[str]) -> bool:
    """True for a comment alone on its line whose words are mostly the next statement's."""
    text = token.string
    if not token.line.strip().startswith("#") or DIRECTIVE.match(text) or REASON.search(text):
        return False
    said = words(text)
    if len(said) < MIN_COMMENT_WORDS:
        return False
    shared = said & words(next_statement(lines, token.start[0] - 1))
    return len(shared) / len(said) >= OVERLAP_LIMIT


def docstring_problems(tree: ast.AST, name: str) -> list[str]:
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        doc = ast.get_docstring(node)
        if doc and "\n" not in doc.strip() and restates_signature(doc, node):
            problems.append(
                f"{name}:{node.lineno}: docstring of {node.name} only restates its signature"
            )
    return problems


def restates_signature(doc: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = [a.arg for a in node.args.args + node.args.kwonlyargs]
    known = words(node.name) | {w for arg in args for w in words(arg)}
    said = {w for w in words(doc) if w not in DOC_FILLER}
    return said <= known


def problems_in(source: str, name: str) -> list[str]:
    try:
        return comment_problems(source, name) + docstring_problems(ast.parse(source), name)
    except (SyntaxError, tokenize.TokenError, IndentationError) as err:
        raise GateError(f"{name}: cannot parse: {err}") from err


def main(argv: list[str]) -> int:
    files = argv[1:]
    if not files:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        found = [p for f in files for p in problems_in(Path(f).read_text(), f)]
    except (GateError, OSError) as err:
        print(f"QG-RD-04 cannot judge: {err}", file=sys.stderr)
        return 2
    for problem in found:
        print(f"QG-RD-04: {problem}")
    print(f"QG-RD-04: {len(found)} finding(s) in {len(files)} file(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
