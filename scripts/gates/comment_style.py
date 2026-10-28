"""QG-RD-04 terseness rules: no framework vocabulary in code text, capped docstrings and blocks.

Reasoning about Principles and Violations belongs in the plan or PR, not in the code.
"""

import ast
import io
import re
import tokenize

DOC_LINES_FUNCTION = 3  # the owner's cap: a docstring that needs more is a design note
DOC_LINES_CLASS = 5  # one more than a function: a class states its invariant
DOC_LINES_MODULE = 6  # a purpose and its one constraint; Usage lines are extra
COMMENT_BLOCK_LINES = 3  # longer than this is prose the code should show
USAGE = re.compile(r"^\s*Usage:")
VIOLATIONS = (
    "Paper Tiger|Distributed Monolith|Leaky Narrative|Infected Core|Black Box"
    "|Computational Friction|Forensic Coding|God Class|God Method|Fossil Comments|Silent Fallback"
)
PRINCIPLE = "Anchor|Shield|Filter|Buffer|Sensor|Engine"
# Principle names are ordinary words: only label use counts, e.g. **Name** or Name ->
LABELED = rf"\*\*(?:{PRINCIPLE})\*\*|(?:{PRINCIPLE})\s*(?:→|->)|(?:→|->)\s*(?:{PRINCIPLE})\b"
LABELED += rf"|\b(?:{PRINCIPLE})\s+[Pp]rinciple"
FRAMEWORK = re.compile(rf"Violation prevented|\b(?:{VIOLATIONS})\b|{LABELED}")


def vocabulary_problems(text: str, where: str) -> list[str]:
    match = FRAMEWORK.search(text)
    if not match:
        return []
    return [f"{where}: framework term {match.group(0)!r} in code text (put it in the plan or PR)"]


def doc_lines(doc: str) -> int:
    return sum(1 for line in doc.splitlines() if line.strip() and not USAGE.match(line))


def docstring_cap(node: ast.AST) -> int:
    if isinstance(node, ast.Module):
        return DOC_LINES_MODULE
    return DOC_LINES_CLASS if isinstance(node, ast.ClassDef) else DOC_LINES_FUNCTION


def docstring_style_problems(tree: ast.AST, name: str) -> list[str]:
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        doc = ast.get_docstring(node)
        if not doc:
            continue
        where = f"{name}:{getattr(node, 'lineno', 1)}"
        problems += vocabulary_problems(doc, where)
        if doc_lines(doc) > docstring_cap(node):
            problems.append(f"{where}: docstring over {docstring_cap(node)} lines")
    return problems


def comment_style_problems(source: str, name: str) -> list[str]:
    problems, run = [], []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        where = f"{name}:{token.start[0]}"
        problems += vocabulary_problems(token.string, where)
        if token.line.strip().startswith("#") and not token.string.startswith("#!"):
            consecutive = run and run[-1] == token.start[0] - 1
            run = [*run, token.start[0]] if consecutive else [token.start[0]]
            if len(run) == COMMENT_BLOCK_LINES + 1:
                problems.append(f"{where}: comment block over {COMMENT_BLOCK_LINES} lines")
    return problems
