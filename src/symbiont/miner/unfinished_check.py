"""A check still red: its latest run in a session failed and no later run of it passed.

Pure. "The same check" is `same_check.py`'s identity. A failure counts only when it is a check
(a runner's own failure output or a known test, lint, type or build tool), so `ls missing` or a
`grep` with no match never holds a stop.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.miner.failure_excerpt import assertion_excerpt, one_line
from symbiont.miner.same_check import check_of, reruns_same_check
from symbiont.records.output_failure import shows_failure
from symbiont.records.schema import Kind, Record

CHECK_NAME_CHARS = 80
EXCERPT_FALLBACK_CHARS = 160
# Tools whose non-zero exit means the work does not pass; `script test` is `npm test` and kin.
_CHECK_TOOLS = frozenset(
    {
        "pytest",
        "py.test",
        "unittest",
        "tox",
        "nox",
        "jest",
        "vitest",
        "mocha",
        "ruff",
        "mypy",
        "pyright",
        "flake8",
        "pylint",
        "eslint",
        "tsc",
        "cargo test",
        "cargo clippy",
        "cargo check",
        "cargo build",
        "go test",
        "go vet",
        "go build",
        "script test",
        "script lint",
        "script build",
        "script typecheck",
    }
)


@dataclass(frozen=True)
class UnfinishedCheck:
    """The latest failed run of a check nothing has passed since."""

    check: str
    excerpt: str
    step: int


def unfinished_check(session: Sequence[Record]) -> UnfinishedCheck | None:
    """The most recent check that is still failing in `session`, or None when all are clear."""
    open_failures: list[Record] = []
    for record in session:
        open_failures = _after(open_failures, record)
    return _described(open_failures[-1]) if open_failures else None


def _after(open_failures: list[Record], record: Record) -> list[Record]:
    """The checks still red once `record` has run: a pass closes its own, a failure replaces."""
    if _passed(record):
        return [f for f in open_failures if not reruns_same_check(f, record)]
    found = check_of(record.command or "") if _failed_check(record) else None
    if found is None:
        return open_failures
    kept = [f for f in open_failures if check_of(f.command or "") != found]
    return [*kept, record]


def _passed(record: Record) -> bool:
    """A command that ran and exited 0 with no runner failure in its output."""
    return record.kind == Kind.COMMAND and record.exit_code == 0 and not shows_failure(record.raw)


def _failed_check(record: Record) -> bool:
    """A command that exited non-zero and is a check, not an answer-by-status or a typo."""
    if record.kind != Kind.COMMAND or record.exit_code in (None, 0):
        return False
    found = check_of(record.command or "")
    return found is not None and (shows_failure(record.raw) or found.tool in _CHECK_TOOLS)


def _described(record: Record) -> UnfinishedCheck:
    """The failed run as a name a person recognizes and one line of what it said."""
    found = check_of(record.command or "")
    parts = [found.tool.removeprefix("script ")] if found else []
    parts += sorted(found.targets) if found else []
    return UnfinishedCheck(" ".join(parts)[:CHECK_NAME_CHARS], _what_it_said(record), record.step)


def _what_it_said(record: Record) -> str:
    """The expected-versus-actual lines, else the last output line, else the exit status."""
    excerpt = one_line(assertion_excerpt(record.raw))
    if excerpt:
        return excerpt
    lines = [line.strip() for line in record.raw.splitlines() if line.strip()]
    if lines:
        return lines[-1][:EXCERPT_FALLBACK_CHARS]
    return f"exit {record.exit_code}"
