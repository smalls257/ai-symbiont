"""What each session cost: turns lost, how every failure ended, and the facts kept per session.

The dashboard's numbers come from these pure
functions over records, not from the page; and "turns lost" is a measured span of actions (a
failure to the next pass of the same program), not a guess from the length of a fix.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from symbiont.miner.attempts import failed
from symbiont.miner.commands import program_words
from symbiont.miner.failure_keys import INTERRUPTS
from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.miner.patterns import StrugglePattern, patterns_of
from symbiont.miner.resolutions import NO_LATER_SUCCESS, NOTHING_CHANGED, PASSED_RESPELLED
from symbiont.miner.screen import PROBES
from symbiont.miner.themes import Codebase, task_label, task_text, themes_of
from symbiont.records.schema import Kind, Record

# Tuned once on sqlglot OpenHands traces; Step 6 of the plan re-measures them on other history.
MAX_SPAN_TURNS = 15  # a failure that never passes is not charged more than this
BURST_FAILURES = 3  # failures within BURST_STEPS steps make a session "struggled"
BURST_STEPS = 10
# The same command passed later but nothing that explains it was shown: no known fix.
_PASSED_AGAIN = frozenset({PASSED_RESPELLED, NOTHING_CHANGED})
# [hypothesis] Minutes of working time one agent turn costs. No source exists for 0.7: it is a
# round guess, labeled "estimated" wherever the page shows hours, and it has not been measured.
MINUTES_PER_TURN = 0.7
_ACTIONS = (Kind.COMMAND, Kind.EDIT, Kind.READ, Kind.AGENT_TURN)


class Outcome(StrEnum):
    """How a failed command ended. The first two share their values with `FixKind`."""

    CODE_FIX = "code_fix"
    CORRECTED_COMMAND = "corrected_command"
    RESPELLED = "respelled"
    NEVER = "never"
    UNCLEAR = "unclear"
    PROBE = "probe"
    INTERRUPT = "interrupt"


@dataclass(frozen=True)
class SessionFacts:
    """What one session was about, how it struggled and what the failures came to."""

    session_id: str
    task_label: str
    themes: frozenset[str]
    patterns: frozenset[StrugglePattern]
    turns_lost: int
    outcomes: Mapping[str, int]
    # Three or more failures within ten steps: the session had a bad stretch.
    struggled: bool = False


def turns_lost(session: Sequence[Record]) -> int:
    """Agent actions from a failure to the next pass of the same program; spans merged."""
    actions = [r for r in session if r.kind in _ACTIONS]
    covered: set[int] = set()
    for position, record in enumerate(actions):
        if failed(record):
            covered.update(range(position, _span_end(actions, position) + 1))
    return len(covered)


def _span_end(actions: Sequence[Record], start: int) -> int:
    """Index of the pass that ends the failure at `start`, else the cap."""
    program = program_words(actions[start].command or "")[0]
    for index in range(start + 1, min(len(actions), start + MAX_SPAN_TURNS + 1)):
        later = actions[index]
        passed = later.kind == Kind.COMMAND and later.exit_code == 0
        if passed and program_words(later.command or "")[0] == program:
            return index
    return min(len(actions) - 1, start + MAX_SPAN_TURNS)


def has_failure_burst(session: Sequence[Record]) -> bool:
    """True when some failure is followed by enough more within a few steps."""
    steps = [r.step for r in session if failed(r)]
    return any(_failures_from(first, steps) >= BURST_FAILURES for first in steps)


def _failures_from(first: int, steps: Sequence[int]) -> int:
    """How many of the failing `steps` fall in the window that opens at `first`."""
    return sum(first <= step < first + BURST_STEPS for step in steps)


def outcome_of(lesson: Lesson) -> Outcome:
    """How the failure behind a (not yet screened) failed-command lesson ended."""
    program = lesson.pain_point.signature.key[0]
    if program in INTERRUPTS:
        return Outcome.INTERRUPT
    if program in PROBES:
        return Outcome.PROBE
    if lesson.fix is FixKind.CODE_FIX:
        return Outcome.CODE_FIX
    if lesson.fix is FixKind.CORRECTED_COMMAND:
        return Outcome.CORRECTED_COMMAND
    if lesson.resolution or lesson.unresolved_because in _PASSED_AGAIN:
        return Outcome.RESPELLED
    return Outcome.NEVER if lesson.unresolved_because == NO_LATER_SUCCESS else Outcome.UNCLEAR


def facts_of(
    sessions: Sequence[Sequence[Record]],
    lessons: Sequence[Lesson],
    codebase: Codebase,
    vocabulary: frozenset[str],
) -> list[SessionFacts]:
    """One row of facts per session, in the order of `sessions`; `lessons` are unscreened."""
    outcomes: dict[str, Counter[str]] = {}
    for lesson in lessons:
        if lesson.pain_point.signature.signal is Signal.FAILED_COMMAND:
            counter = outcomes.setdefault(lesson.pain_point.session_id, Counter())
            counter[outcome_of(lesson).value] += 1
    return [_facts(s, codebase, vocabulary, outcomes.get(s[0].session_id)) for s in sessions]


def _facts(
    session: Sequence[Record],
    codebase: Codebase,
    vocabulary: frozenset[str],
    outcomes: Counter[str] | None,
) -> SessionFacts:
    """The facts of one session."""
    return SessionFacts(
        session_id=session[0].session_id,
        task_label=task_label(session),
        themes=themes_of(task_text(session), vocabulary),
        patterns=patterns_of(session, codebase),
        turns_lost=turns_lost(session),
        outcomes=dict(outcomes or {}),
        struggled=has_failure_burst(session),
    )
