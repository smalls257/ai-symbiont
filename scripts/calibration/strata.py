"""Strata labels for pool tasks: which sqlglot subsystem a gold patch touches, and how big it is.

Violation prevented: **Paper Tiger** in the Act 2 pool. A screen that takes the smallest gold
patches meets "run 40 tasks" and fails the need (one developer's varied week), because the
smallest patches are near-identical one-line dialect fixes. The labels let the screen see variety.

Pure functions over a diff string and a number: no disk, no network. Deployed next to staged.py.
"""

import re

# Order matters only for readability: a path belongs to the first matching label. Reason for the
# grouping: sqlglot's top-level modules that a maintainer thinks of as one "area" of work.
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
# Size bands on changed lines (added + removed). The pool cap is 60 (build_pool.MAX_GOLD_LINES):
# below 10 is a one-liner, 10-29 a small fix, 30-59 a real change.
SMALL_BELOW = 10
LARGE_FROM = 30

_NEW_PATH = re.compile(r"^\+\+\+ b/(\S+)", re.MULTILINE)


def _label_of_path(path: str) -> str:
    for label, pattern in SUBSYSTEM_PATTERNS:
        if pattern.search(path):
            return label
    return OTHER


def subsystem_of(patch: str) -> str:
    """The subsystem label of a gold patch, read from its `+++ b/<path>` lines.

    expressions.py is ignored when any other path is present (it only carries the node class a
    change in another area needs). Two or more other labels give "multi". A patch with no
    recognizable path is "other", not an error: the label is a stratum, not a claim.
    """
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
