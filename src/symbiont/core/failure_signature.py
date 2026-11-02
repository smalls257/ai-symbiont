"""The normalized signature of one failure: which test, and what it said.

Two failures are the same when the failing test and the message match once numbers, paths and
hashes are normalized. A command and an exception class alone never match, because a hundred
different assertions share them. Pure: text in, text out.
"""

import re
from dataclasses import dataclass

DETAIL_CHARS = 90
_TEST_ID = re.compile(r"^(?:FAILED|ERROR)\s+\S*?::([\w\[\].-]+)", re.M)
_TEST_HEADER = re.compile(r"^_{3,}\s+([\w.\[\]-]+)\s+_{3,}$", re.M)
_ASSERT_LINE = re.compile(r"^E\s+(\S.*)$", re.M)
_EXCEPTION_LINE = re.compile(r"^\s*(?:[\w.]+\.)?\w*(?:Error|Exception|Failure)\b.*$", re.M)
_PATH = re.compile(r"\S*/\S*")
_HASH = re.compile(r"\b(?:0x)?[0-9a-f]{7,40}\b")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class FailureSignature:
    """The failing test names (may be empty) and the normalized message."""

    tests: frozenset[str]
    message: str


def failure_detail(output: str) -> str:
    """The message line that says what failed, as printed and trimmed; empty when there is none."""
    line = _message_line(output)
    return line if len(line) <= DETAIL_CHARS else line[: DETAIL_CHARS - 3] + "..."


def failure_signature(output: str) -> FailureSignature | None:
    """The signature of the failure in `output`, or None when it names no message to compare."""
    line = _message_line(output)
    if not line:
        return None
    tests = frozenset(_TEST_ID.findall(output) + _TEST_HEADER.findall(output))
    return FailureSignature(tests, _normalized(line))


def same_failure(live: str, stored: str) -> bool:
    """Whether two outputs show the same failure; one with no message to compare never matches."""
    first, second = failure_signature(live), failure_signature(stored)
    if first is None or second is None or first.message != second.message:
        return False
    return not (first.tests and second.tests) or bool(first.tests & second.tests)


def _message_line(output: str) -> str:
    """The last assertion line (`E ...`), else the last exception line, else empty."""
    asserted = [match.strip() for match in _ASSERT_LINE.findall(output)]
    if asserted:
        return asserted[-1]
    raised = [match.strip() for match in _EXCEPTION_LINE.findall(output)]
    return raised[-1] if raised else ""


def _normalized(line: str) -> str:
    """The line with paths, hashes and numbers replaced, whitespace collapsed."""
    line = _PATH.sub("<path>", line)
    line = _HASH.sub("<hash>", line)
    line = _NUMBER.sub("<n>", line)
    return " ".join(line.split())
