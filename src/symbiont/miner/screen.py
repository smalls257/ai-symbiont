"""Screening: which mined groups of trouble become lessons, and why the rest are held back.

A group is every lesson with one signature. Counting repeats of a trap with no shown fix teaches
nothing, and a threshold nobody measured is a magic number, so the
rules are few, named and counted: a failed-command group needs a known fix before it may be
taught, then `min_sessions` distinct sessions. Every held group is counted under the first reason
that applies and shown; nothing is dropped quietly. Pure: lessons in, lessons out.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from symbiont.miner.failure_keys import is_bare_exit
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal, Signature

# Read-only look-around programs: a failure of one is the agent feeling its way, not a trap.
PROBES = frozenset(
    {"ls", "cat", "head", "tail", "find", "stat", "file", "which", "pwd", "wc", "grep", "rg"}
)
# A correction or a reviewer's flag is a person speaking: one is enough, and it is never held.
EXEMPT_SIGNALS = frozenset({Signal.CORRECTION, Signal.REVIEW_FLAG})


class HoldReason(StrEnum):
    """Why a group was not turned into a lesson, in the order the reasons are tried."""

    IGNORED = "ignored"
    NO_FIX_SHOWN = "no_fix_shown"
    NO_MESSAGE = "no_message"
    PROBE_COMMAND = "probe_command"
    TOO_FEW_SESSIONS = "too_few_sessions"


@dataclass(frozen=True)
class ScreenRules:
    """The one threshold and the patterns the developer set aside."""

    # Sessions a lesson-grade group must appear in. 2 is the least that says "it repeats"; it was
    # tuned on three or four sessions, so it is a setting (`symbiont settings mining`), not a fact.
    min_sessions: int = 2
    ignored: frozenset[Signature] = frozenset()


@dataclass(frozen=True)
class Screened:
    """The lessons that stay, how many groups were held per reason, and the struggle."""

    kept: list[Lesson]
    held: dict[HoldReason, int]
    # Lessons of groups held for NO_FIX_SHOWN: where agents struggled, for the cost view.
    struggle: list[Lesson]


def screen(lessons: Sequence[Lesson], rules: ScreenRules) -> Screened:
    """Keep the lessons of groups no reason holds back; count every held group once."""
    groups: dict[Signature, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        groups[lesson.pain_point.signature].append(lesson)
    kept: list[Lesson] = []
    struggle: list[Lesson] = []
    held: dict[HoldReason, int] = {}
    for signature, group in groups.items():
        reason = hold_reason(signature, group, rules)
        if reason is None:
            kept.extend(group)
            continue
        held[reason] = held.get(reason, 0) + 1
        if reason is HoldReason.NO_FIX_SHOWN:
            struggle.extend(group)
    return Screened(kept, held, struggle)


def hold_reason(
    signature: Signature, group: Sequence[Lesson], rules: ScreenRules
) -> HoldReason | None:
    """The first reason to hold the group back, or None when it is lesson-grade."""
    if signature in rules.ignored:
        return HoldReason.IGNORED
    if signature.signal in EXEMPT_SIGNALS:
        return None
    if signature.signal is Signal.FAILED_COMMAND:
        return _failed_command_reason(signature, group, rules)
    return _too_few_sessions(group, rules)


def _failed_command_reason(
    signature: Signature, group: Sequence[Lesson], rules: ScreenRules
) -> HoldReason | None:
    """A failed command needs a known fix, a message to compare, and to not be a probe."""
    if not any(lesson.fix is not None for lesson in group):
        return HoldReason.NO_FIX_SHOWN
    if is_bare_exit(signature.key[-1]):
        return HoldReason.NO_MESSAGE
    if signature.key[0] in PROBES:
        return HoldReason.PROBE_COMMAND
    return _too_few_sessions(group, rules)


def _too_few_sessions(group: Sequence[Lesson], rules: ScreenRules) -> HoldReason | None:
    """TOO_FEW_SESSIONS when the group is seen in fewer sessions than the rules ask."""
    sessions = {lesson.pain_point.session_id for lesson in group}
    return HoldReason.TOO_FEW_SESSIONS if len(sessions) < rules.min_sessions else None
