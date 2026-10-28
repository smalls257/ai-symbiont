"""Strata for pool tasks: the sqlglot subsystem a gold patch touches, and its size band."""

import re

# a path takes the first matching label
SUBSYSTEM_PATTERNS = (
    ("dialects", re.compile(r"(^|/)dialects/")),
    ("parser", re.compile(r"(^|/)(parser|tokens)\.py$")),
    ("optimizer", re.compile(r"(^|/)optimizer/")),
    ("executor", re.compile(r"(^|/)executor/")),
    ("generator", re.compile(r"(^|/)generator\.py$")),
    ("expressions", re.compile(r"(^|/)expressions\.py$")),
)
OTHER = "other"
MULTI = "multi"  # two or more non-expressions areas touched by one patch
EXPRESSIONS = "expressions"
# changed lines: one-liner, small fix, real change (the pool caps at 60)
SMALL_BELOW = 10
LARGE_FROM = 30

_NEW_PATH = re.compile(r"^\+\+\+ b/(\S+)", re.MULTILINE)


def _label_of_path(path: str) -> str:
    for label, pattern in SUBSYSTEM_PATTERNS:
        if pattern.search(path):
            return label
    return OTHER


def subsystem_of(patch: str) -> str:
    """The area a gold patch touches; expressions.py counts only when it is the sole file."""
    labels = {_label_of_path(path) for path in _NEW_PATH.findall(patch)}
    if not labels:
        return OTHER
    rest = labels - {EXPRESSIONS}
    if not rest:
        return EXPRESSIONS
    return MULTI if len(rest) > 1 else next(iter(rest))


def size_band(changed_lines: int) -> str:
    """S below SMALL_BELOW changed lines, M below LARGE_FROM, L from there up."""
    if changed_lines < SMALL_BELOW:
        return "S"
    return "M" if changed_lines < LARGE_FROM else "L"
