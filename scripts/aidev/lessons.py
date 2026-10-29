"""General lessons from AIDev: a human flagged an agent's hunk, a later commit in the PR fixed it.

A lesson has three parts: what happened, how it was resolved, the check to run. Every word comes
from a template plus short extracted fields (file path, function name, issue kind, line counts),
never from the reviewer's or the patch's text, which stay under their own licenses and are
untrusted. A comment whose kind no rule names, or a flag no later commit answered, gives no lesson
and is counted by reason, never filled with a guess. Pure: labels and comment text in, lessons out.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from flags import Commit, Unit

MAX_BODY_CHARS = 2000  # a longer comment is classified on its opening, where the point usually is
TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")


class IssueKind(StrEnum):
    """The general, transferable kinds of review finding a lesson may teach."""

    TESTS_MISSING = "tests_missing"
    ERROR_HANDLING = "error_handling"
    WRONG_MODULE = "wrong_module"
    API_MISUSE = "api_misuse"
    NAMING_CONVENTION = "naming_convention"


# First match wins, in this order: the narrower, more checkable kinds first.
_RULES: tuple[tuple[IssueKind, re.Pattern[str]], ...] = (
    (
        IssueKind.TESTS_MISSING,
        re.compile(
            r"\b(add|adding|write|include|missing|need|needs|no|without|should have)\b"
            r"[^.\n]{0,60}\btests?\b|\b(test )?coverage\b|\bunit tests?\b|\bnot (covered|tested)\b"
        ),
    ),
    (
        IssueKind.ERROR_HANDLING,
        re.compile(
            r"\berror handling\b|\bhandle (the |this |that )?(error|exception|failure|none)\b"
            r"|\btry\s*/\s*except\b|\bexcept\b|\bexceptions?\b|\braises?\b|\bswallow"
            r"|\bfails? silently\b|\bbare except\b|\berrors? (handling|message|case)\b"
            r"|\b(handle|catch|log|propagate|surface)\b[^.\n]{0,20}\berrors?\b|\btimeouts?\b"
        ),
    ),
    (
        IssueKind.WRONG_MODULE,
        re.compile(
            r"\bmov(e|ed|ing)\b[^.\n]{0,40}\b(to|into)\b"
            r"|\bshould (be|live|go) in\b|\bbelongs? (in|to)\b|\bseparate (file|module)\b"
            r"|\bwrong (file|module|place|location|package|directory)\b|\bits own (file|module)\b"
        ),
    ),
    (
        IssueKind.API_MISUSE,
        re.compile(
            r"\bdeprecated\b|\bdoes(n't| not) (exist|accept|support|take)\b|\bshould (use|call)\b"
            r"|\bwrong (argument|parameter|api|method|function|type)\b|\bsignature\b"
            r"|\b(use|using) `?[\w.]+(\(\))?`? instead\b|\binstead of (calling|using)\b"
        ),
    ),
    (
        IssueKind.NAMING_CONVENTION,
        re.compile(
            r"\bnaming\b|\brenam(e|ing)\b|\b(better|clearer|descriptive|variable|function) name\b"
            r"|\bconventions?\b|\bsnake_?case\b|\bcamel_?case\b|\bpep ?8\b"
            r"|\bconsistent with (the )?(rest|other|existing)\b|\bname (it|this|the)\b"
            r"|\btype (hints?|annotations?)\b|\bdocstrings?\b|\bunused imports?\b"
            r"|\bimports? (at|to|on) the top\b"
        ),
    ),
)

PROBLEM = {
    IssueKind.TESTS_MISSING: "the change came without tests that exercise it",
    IssueKind.ERROR_HANDLING: "a failure path was missing, too broad or silently swallowed",
    IssueKind.WRONG_MODULE: "the code was put in the wrong module or place",
    IssueKind.API_MISUSE: "an API was called the wrong way, or a deprecated one was used",
    IssueKind.NAMING_CONVENTION: "a name or the style broke the project's conventions",
}
CHECK = {
    IssueKind.TESTS_MISSING: (
        "Before you finish, add or update a test that fails without the change and passes with it."
    ),
    IssueKind.ERROR_HANDLING: (
        "Before you finish, check each new call that can fail: catch only the errors you expect, "
        "and raise or log the rest with context, never pass silently."
    ),
    IssueKind.WRONG_MODULE: (
        "Before you add code, find where similar code already lives in the project and put it "
        "there."
    ),
    IssueKind.API_MISUSE: (
        "Before you call an API, read its current signature and deprecation notes for the "
        "installed version, and follow how the project already calls it."
    ),
    IssueKind.NAMING_CONVENTION: (
        "Before you finish, compare each new name with the neighboring code and match the "
        "project's naming and style conventions."
    ),
}


def classify(body: str) -> IssueKind | None:
    """The first kind whose rule matches the comment, or None if it is not a general kind."""
    text = body[:MAX_BODY_CHARS].lower()
    return next((kind for kind, rule in _RULES if rule.search(text)), None)


def is_test_path(path: str) -> bool:
    """A test module or anything under a tests directory."""
    return bool(TEST_PATH.search(path))


@dataclass(frozen=True)
class Resolution:
    """The later commit that answered a flag, in counts only."""

    commit_index: int
    added: int  # lines the fix added to the flagged file (0 when only tests changed)
    removed: int
    tests_changed: bool  # a test file changed after the flag, up to and including the fix


def resolution(unit: Unit, commits: Sequence[Commit], kind: IssueKind) -> Resolution | None:
    """What answered a human flag: the rework of its lines, or, for missing tests, a test change."""
    flagged = unit.human_at
    if flagged is None:
        raise ValueError("resolution asked for a unit no human flagged")
    if unit.changed_at is not None:
        added, removed = _line_counts(commits[unit.changed_at], unit.path)
        tests = _tests_changed(commits[flagged + 1 : unit.changed_at + 1])
        return Resolution(unit.changed_at, added, removed, tests)
    if kind is IssueKind.TESTS_MISSING:
        later = commits[flagged + 1 :]
        first = next((i for i, c in enumerate(later) if _tests_changed([c])), None)
        if first is not None:
            return Resolution(flagged + 1 + first, 0, 0, tests_changed=True)
    return None


def _line_counts(commit: Commit, path: str) -> tuple[int, int]:
    state = (commit.files or {}).get(path)
    hunks = state.hunks if state is not None and state.hunks is not None else ()
    return sum(len(h.added) for h in hunks), sum(len(h.removed) for h in hunks)


def _tests_changed(commits: Sequence[Commit]) -> bool:
    return any(is_test_path(name) for c in commits for name in (c.files or {}))


@dataclass(frozen=True)
class Lesson:
    """One human-verified general lesson, in short extracted fields."""

    lesson_id: str
    repo: str
    agent: str
    kind: IssueKind
    path: str
    function: str | None
    fix: Resolution

    def where(self) -> str:
        """The function and file the lesson is about, as prose."""
        if self.function:
            return f"`{self.function}` in `{self.path}`"
        return f"`{self.path}`"

    def what_happened(self) -> str:
        """Part one: what the reviewer flagged."""
        return (
            f"In a Python repository, a reviewer flagged the agent's new lines in "
            f"{self.where()}: {PROBLEM[self.kind]}."
        )

    def how_resolved(self) -> str:
        """Part two: the later commit that fixed it."""
        if self.fix.added == 0 and self.fix.removed == 0:
            return "A later commit in the same pull request added or changed tests for it."
        tests = " and changed the tests" if self.fix.tests_changed else ""
        return (
            f"A later commit in the same pull request reworked those lines "
            f"({self.fix.added} added, {self.fix.removed} removed){tests}."
        )

    def check(self) -> str:
        """Part three: the check to run next time."""
        return CHECK[self.kind]

    def text(self) -> str:
        """The three parts as one paragraph."""
        return f"{self.what_happened()} {self.how_resolved()} {self.check()}"


def lesson_id(pr_id: int, unit: Unit) -> str:
    """A stable id for one flagged unit."""
    key = f"{pr_id}:{unit.path}:{unit.commit_index}:{unit.hunk.added[:1]}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]
