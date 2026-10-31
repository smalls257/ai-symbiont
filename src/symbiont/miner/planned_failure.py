"""Planned failures: a test the agent wrote or edited this session, failing as an assertion.

TDD red is not a mistake: writing the test first and watching it fail is the method, so a lesson
"this failed last time" would teach the wrong thing. A broken import, a typo or an existing test
broken by an edit is a mistake. Pure: records in, a kind out.
"""

import re
from collections.abc import Sequence
from enum import StrEnum

from symbiont.miner.failing_tests import failing_test_files, same_file
from symbiont.records.schema import Kind, Record

_CODE_ERROR = re.compile(
    r"\b(?:ImportError|ModuleNotFoundError|SyntaxError|IndentationError|TypeError|NameError"
    r"|AttributeError|UnboundLocalError)\b"
)
_ASSERTION = re.compile(r"\bAssertionError\b|^E\s+assert\b|^assert\b|FAILED .*\bassert\b", re.M)
_TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$|(?:^|/)tests?/")
_PATH_ARGUMENT = re.compile(r"[\w./-]+\.py")


class ErrorKind(StrEnum):
    """What the error line says broke."""

    ASSERTION = "assertion"  # a test's own check failed
    CODE_ERROR = "code_error"  # import, module, syntax, type, name or attribute error
    UNNAMED = "unnamed"  # neither: a traceback in code, a plain non-zero exit


class FailureKind(StrEnum):
    """Whether a failure is part of the plan or evidence of a mistake."""

    PLANNED = "planned"
    MISTAKE = "mistake"


def error_kind(output: str) -> ErrorKind:
    """Classify the output: a code error outranks an assertion (the run never reached the check)."""
    if _CODE_ERROR.search(output):
        return ErrorKind.CODE_ERROR
    return ErrorKind.ASSERTION if _ASSERTION.search(output) else ErrorKind.UNNAMED


def failure_kind(failed: Record, earlier: Sequence[Record]) -> FailureKind:
    """PLANNED only for an assertion in a test edited earlier this session (TDD red, not a mistake).

    An import or name error, an untouched test or a traceback in non-test code is a mistake.
    """
    if error_kind(failed.raw) is not ErrorKind.ASSERTION:
        return FailureKind.MISTAKE
    touched = _tests_edited(earlier)
    ran = _tests_run(failed)
    planned = any(same_file(run, edited) for run in ran for edited in touched)
    return FailureKind.PLANNED if planned else FailureKind.MISTAKE


def _tests_edited(earlier: Sequence[Record]) -> set[str]:
    """Test files created or edited by the session's earlier edit records."""
    paths = {path for record in earlier if record.kind is Kind.EDIT for path in record.files}
    return {path for path in paths if _TEST_FILE.search(path)}


def _tests_run(failed: Record) -> set[str]:
    """Test files the failing command names or its output reports as failing."""
    named = {path for path in _PATH_ARGUMENT.findall(failed.command or "")}
    return named | set(failing_test_files(failed))
