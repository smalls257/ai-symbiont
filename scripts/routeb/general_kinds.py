"""Label a public sqlglot task "feature" (adds a capability) or "bug" (corrects behavior).

The rule reads the issue title and body and the gold patch's source lines, in a fixed order, so
the same row always gets the same kind and the reason names which step decided it. Pure.
"""

import re
from dataclasses import dataclass
from enum import StrEnum


class TaskKind(StrEnum):
    """What the gold patch does for the user."""

    FEATURE = "feature"
    BUG = "bug"


class KindReason(StrEnum):
    """Which step of the rule decided the kind."""

    REQUEST_TITLE = "request-title"
    FEATURE_TEMPLATE = "feature-template"
    BUG_TITLE = "bug-title"
    UNSUPPORTED_TITLE = "unsupported-title"
    ADDITIVE_PATCH = "additive-patch"
    CORRECTIVE_PATCH = "corrective-patch"


RULE = (
    "first match: support/add/allow/implement title or feature template = feature; fault title "
    "(incorrect, error, fails, bug...) = bug; not-supported title = feature; sqlglot/ patch adding "
    "a class, def or mapping entry with removed <= added/4 = feature; else bug"
)
REQUEST = re.compile(
    r"^\W*(\[[^]]*\]\s*)*(feat|feature|support|add|allow|implement|include)\b"
    r"|\b(add|adding|include) support\b|\bsupport for\b|\bfeature request\b",
    re.IGNORECASE,
)
TEMPLATE = "Is your feature request related to a problem"
FAULT = re.compile(
    r"\b(incorrect\w*|wrong\w*|bug|inconsistent|erroneous\w*|broken|regression|invalid|error"
    r"|errors|fail\w*|issue|crash\w*|false positive|doesn't|does not|not working|reversed"
    r"|dropp\w*|lost|loses|mangl\w*)\b",
    re.IGNORECASE,
)
UNSUPPORTED = re.compile(r"\b(not supported|unsupported|no support)\b", re.IGNORECASE)
DEFINITION = re.compile(r"^\s*(class|def) ")
ENTRY = re.compile(r"""^\s*(["'][\w ]+["']|exp\.\w+|TokenType\.\w+)\s*[:,]""")
ADDED_PER_REMOVED = 4


@dataclass(frozen=True)
class PatchShape:
    """Non-blank changed lines of the gold patch under sqlglot/, and what the added ones define."""

    added: int
    removed: int
    definitions: int
    entries: int

    def is_additive(self) -> bool:
        """New definitions or mapping entries, and little removed: a new capability."""
        grows = self.definitions + self.entries > 0
        return grows and self.removed * ADDED_PER_REMOVED <= self.added


def patch_shape(patch: str) -> PatchShape:
    """Count the gold patch's source changes; tests, docs and README are ignored."""
    counts = {"added": 0, "removed": 0, "definitions": 0, "entries": 0}
    in_source = False
    for line in patch.splitlines():
        if line.startswith("diff --git"):
            in_source = line.split(" b/")[-1].startswith("sqlglot/")
        if not in_source or line.startswith(("+++", "---")) or not line[1:].strip():
            continue
        if line.startswith("+"):
            counts["added"] += 1
            counts["definitions"] += bool(DEFINITION.match(line[1:]))
            counts["entries"] += bool(ENTRY.match(line[1:]))
        elif line.startswith("-"):
            counts["removed"] += 1
    return PatchShape(**counts)


def issue_title(statement: str) -> str:
    """The first non-blank line of the issue."""
    return next((line.strip() for line in statement.splitlines() if line.strip()), "")


def task_kind(statement: str, patch: str) -> tuple[TaskKind, KindReason]:
    """The kind of one task and the rule step that decided it."""
    title = issue_title(statement)
    if REQUEST.search(title):
        return TaskKind.FEATURE, KindReason.REQUEST_TITLE
    if TEMPLATE in statement:
        return TaskKind.FEATURE, KindReason.FEATURE_TEMPLATE
    if FAULT.search(title):
        return TaskKind.BUG, KindReason.BUG_TITLE
    if UNSUPPORTED.search(title):
        return TaskKind.FEATURE, KindReason.UNSUPPORTED_TITLE
    if patch_shape(patch).is_additive():
        return TaskKind.FEATURE, KindReason.ADDITIVE_PATCH
    return TaskKind.BUG, KindReason.CORRECTIVE_PATCH
