"""Planned failures: a test the agent wrote or edited this session, failing as an assertion.

TDD red is not a mistake: the test fails first on an assertion or on a name the project has yet
to write. A third-party import, a typo or an existing test broken by an edit is. Pure.
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
_CANNOT_IMPORT = re.compile(r"cannot import name '\w+' from '([\w.]+)'")
_NO_ATTRIBUTE = re.compile(r"module '([\w.]+)' has no attribute '\w+'")
_NO_MODULE = re.compile(r"No module named '([\w.]+)'")
_UNDEFINED = re.compile(r"name '(\w+)' is not defined")
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
    """PLANNED for a TDD red: an assertion or a not-yet-defined project name in a touched test.

    Third-party imports, untouched tests, syntax and type errors, non-test tracebacks are mistakes.
    """
    touched = _tests_edited(earlier)
    if not any(same_file(run, edited) for run in _tests_run(failed) for edited in touched):
        return FailureKind.MISTAKE
    kind = error_kind(failed.raw)
    if kind is ErrorKind.ASSERTION or (
        kind is ErrorKind.CODE_ERROR and _all_unwritten_project_names(failed.raw, earlier)
    ):
        return FailureKind.PLANNED
    return FailureKind.MISTAKE


def _all_unwritten_project_names(output: str, earlier: Sequence[Record]) -> bool:
    """Every error line is about a name or module the project itself has yet to define."""
    lines = [line for line in output.splitlines() if _CODE_ERROR.search(line)]
    owned = _project_packages(earlier)
    return all(_about_project_name(line, owned, earlier) for line in lines)


def _about_project_name(line: str, owned: set[str], earlier: Sequence[Record]) -> bool:
    """One error line names something inside the project (or a name only the test uses)."""
    for pattern in (_CANNOT_IMPORT, _NO_ATTRIBUTE, _NO_MODULE):
        found = pattern.search(line)
        if found:
            return found.group(1).split(".")[0] in owned
    undefined = _UNDEFINED.search(line)
    return bool(undefined) and _only_tests_use(undefined.group(1), earlier)


def _project_packages(earlier: Sequence[Record]) -> set[str]:
    """Top-level package names of every file the session touched or read (`src/` is skipped)."""
    names = set()
    for record in earlier:
        for path in record.files:
            parts = [part for part in path.split("/") if part not in ("", ".", "src")]
            names.add(parts[0].removesuffix(".py") if parts else "")
    return names - {""}


def _only_tests_use(name: str, earlier: Sequence[Record]) -> bool:
    """The name is added in an edited test file and in no edit of non-test code."""
    in_tests = in_code = False
    for record in earlier:
        if record.kind is Kind.EDIT and name in (record.diff or ""):
            is_test = any(_TEST_FILE.search(path) for path in record.files)
            in_tests, in_code = in_tests or is_test, in_code or not is_test
    return in_tests and not in_code


def _tests_edited(earlier: Sequence[Record]) -> set[str]:
    """Test files created or edited by the session's earlier edit records."""
    paths = {path for record in earlier if record.kind is Kind.EDIT for path in record.files}
    return {path for path in paths if _TEST_FILE.search(path)}


def _tests_run(failed: Record) -> set[str]:
    """Test files the failing command names or its output reports as failing."""
    named = {path for path in _PATH_ARGUMENT.findall(failed.command or "")}
    return named | set(failing_test_files(failed))
