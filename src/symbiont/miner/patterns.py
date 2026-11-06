"""How a session's struggle looks: eight named patterns, each a count over one session.

Each pattern names the help that fits, or says there is nothing to teach. The thresholds were
tuned once on sqlglot OpenHands traces (2,678 sessions) and are re-measured, not retuned, on other
history in Step 6 of docs/superpowers/plans/2026-11-06-harness-neutral-mining-curation.md.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum

from symbiont.miner.attempts import failed, is_test_run
from symbiont.miner.changes import applied_edit
from symbiont.miner.churn import churn
from symbiont.miner.commands import inline_script_program, normalise_command, program_words
from symbiont.miner.screen import PROBES
from symbiont.miner.themes import Codebase, is_test_path
from symbiont.records.schema import Kind, Record

PYTEST_NO_TESTS = (4, 5)  # usage error; nothing collected
INLINE_TRIALS = 3
SCRATCH_EDITS = 8
THRASH_EDITS = 5
API_ERROR_WINDOW = 4  # steps after a codebase edit
PROBE_MISSES = 5
RERUN_PASSES = 3
RERUN_WINDOW = 5  # records after a failure that may hold its pass
_API_ERROR = re.compile(r"\b(AttributeError|TypeError|NameError)\b")
_ERROR_TAIL = 600  # the end of the output, where the error is


class StrugglePattern(StrEnum):
    """One way a session's struggle looks."""

    TESTS_NOT_FOUND = "tests_not_found"
    INLINE_TRIAL = "inline_trial"
    SCRATCH_DEBUG = "scratch_debug"
    EDIT_THRASH = "edit_thrash"
    WRONG_API = "wrong_api"
    WRONG_PLACE = "wrong_place"
    RERUNNING = "rerunning"
    ENDED_FAILING = "ended_failing"


# The plain words shown beside each pattern: the help that fits, or that there is none to give.
HELP: Mapping[StrugglePattern, str] = {
    StrugglePattern.TESTS_NOT_FOUND: "lesson: where the tests live",
    StrugglePattern.INLINE_TRIAL: "doc or helper: a ready-made repro script",
    StrugglePattern.SCRATCH_DEBUG: "doc: how to reproduce a bug here",
    StrugglePattern.EDIT_THRASH: "lesson: the right extension point",
    StrugglePattern.WRONG_API: "lesson: the internal API in this area",
    StrugglePattern.WRONG_PLACE: "doc: a map of the repository",
    StrugglePattern.RERUNNING: "nothing to teach: struggle",
    StrugglePattern.ENDED_FAILING: "a human look",
}
# Where no lesson helps: the agent re-ran a thing until it passed, or the session never got there.
NOTHING_TO_TEACH = frozenset({StrugglePattern.RERUNNING, StrugglePattern.ENDED_FAILING})


def patterns_of(session: Sequence[Record], codebase: Codebase) -> frozenset[StrugglePattern]:
    """The patterns one session shows; a clean session shows none."""
    return frozenset(p for p, shows in _DETECTORS.items() if shows(session, codebase))


def _tests_not_found(session: Sequence[Record], codebase: Codebase) -> bool:
    return any(failed(r) and is_test_run(r) and r.exit_code in PYTEST_NO_TESTS for r in session)


def _inline_trial(session: Sequence[Record], codebase: Codebase) -> bool:
    trials = [r for r in session if failed(r) and inline_script_program(r.command or "")]
    return len(trials) >= INLINE_TRIALS


def _scratch_debug(session: Sequence[Record], codebase: Codebase) -> bool:
    outside = [r for r in session if _applied_to(r) and not codebase.contains(r.files[0])]
    return len(outside) >= SCRATCH_EDITS


def _edit_thrash(session: Sequence[Record], codebase: Codebase) -> bool:
    rows = churn([session], codebase.repo_names)
    return any(row.edits >= THRASH_EDITS and not is_test_path(row.file) for row in rows)


def _wrong_api(session: Sequence[Record], codebase: Codebase) -> bool:
    last_edit = None
    for record in session:
        if _applied_to(record) and codebase.contains(record.files[0]):
            last_edit = record.step
        elif _errs_soon_after(record, last_edit):
            return True
    return False


def _wrong_place(session: Sequence[Record], codebase: Codebase) -> bool:
    misses = [r for r in session if failed(r) and program_words(r.command or "")[0] in PROBES]
    return len(misses) >= PROBE_MISSES


def _rerunning(session: Sequence[Record], codebase: Codebase) -> bool:
    attempts = [r for r in session if r.kind in (Kind.COMMAND, Kind.EDIT)]
    passed = sum(_passes_unchanged(attempts[i], attempts[i + 1 :]) for i in range(len(attempts)))
    return passed >= RERUN_PASSES


def _ended_failing(session: Sequence[Record], codebase: Codebase) -> bool:
    tests = [r for r in session if is_test_run(r)]
    return bool(tests) and tests[-1].exit_code not in (None, 0)


def _applied_to(record: Record) -> bool:
    """An applied edit that names a file."""
    return applied_edit(record) and bool(record.files)


def _errs_soon_after(record: Record, edit_step: int | None) -> bool:
    """A failure right after the last codebase edit whose output names a wrong-API error."""
    if not failed(record) or edit_step is None:
        return False
    close = 0 <= record.step - edit_step <= API_ERROR_WINDOW
    return close and _API_ERROR.search(record.raw[-_ERROR_TAIL:]) is not None


def _passes_as(record: Record, same: tuple[str, str]) -> bool:
    """A passing command with the same program and target."""
    return (
        record.kind == Kind.COMMAND
        and record.exit_code == 0
        and normalise_command(record.command or "")[:2] == same
    )


def _passes_unchanged(attempt: Record, later: Sequence[Record]) -> bool:
    """A failed command that passed within a few records with no edit in between."""
    if not failed(attempt):
        return False
    same = normalise_command(attempt.command or "")[:2]
    for record in later[:RERUN_WINDOW]:
        if record.kind == Kind.EDIT:
            return False
        if _passes_as(record, same):
            return True
    return False


_DETECTORS: Mapping[StrugglePattern, Callable[[Sequence[Record], Codebase], bool]] = {
    StrugglePattern.TESTS_NOT_FOUND: _tests_not_found,
    StrugglePattern.INLINE_TRIAL: _inline_trial,
    StrugglePattern.SCRATCH_DEBUG: _scratch_debug,
    StrugglePattern.EDIT_THRASH: _edit_thrash,
    StrugglePattern.WRONG_API: _wrong_api,
    StrugglePattern.WRONG_PLACE: _wrong_place,
    StrugglePattern.RERUNNING: _rerunning,
    StrugglePattern.ENDED_FAILING: _ended_failing,
}
