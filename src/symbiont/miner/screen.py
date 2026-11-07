"""Screening: which mined groups of trouble become lessons, and why the rest are held back.

A group is every lesson with one signature. Repeats of a trap with no shown fix teach nothing, so
a failed-command group needs a known fix, recurring in `min_sessions` distinct sessions, on a
script that outlives its session. Every held group is counted under the first reason that
applies and shown; nothing is dropped quietly. Pure: lessons in, lessons out.
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
# A loop is the agent repeating itself inside one session: once is already the finding.
EXEMPT_SIGNALS = frozenset({Signal.CORRECTION, Signal.REVIEW_FLAG, Signal.LOOP})
# The target a script typed into the command shares (`python -c`, `python - <<EOF`).
INLINE_TARGET = "<inline>"


class HoldReason(StrEnum):
    """Why a group was not turned into a lesson, in the order the reasons are tried."""

    IGNORED = "ignored"
    NO_FIX_SHOWN = "no_fix_shown"
    NO_MESSAGE = "no_message"
    PROBE_COMMAND = "probe_command"
    THROWAWAY_SCRIPT = "throwaway_script"
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
    """Keep lesson-grade groups, count each held group once; an ignored one is counted, still kept.

    Ignoring only hides on read (`Store.lessons`), so Restore after a re-mine needs no new mining.
    """
    groups: dict[Signature, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        groups[lesson.pain_point.signature].append(lesson)
    kept: list[Lesson] = []
    struggle: list[Lesson] = []
    held: dict[HoldReason, int] = {}
    for signature, group in groups.items():
        reason = hold_reason(signature, group, rules)
        if reason is None:
            kept.extend(_taught(signature, group))
            if signature in rules.ignored:
                held[HoldReason.IGNORED] = held.get(HoldReason.IGNORED, 0) + 1
            continue
        held[reason] = held.get(reason, 0) + 1
        if reason is HoldReason.NO_FIX_SHOWN:
            struggle.extend(group)
    return Screened(kept, held, struggle)


def taught_since_the_fix_rule(lessons: Sequence[Lesson], rules: ScreenRules) -> list[Lesson]:
    """`lessons` as today's screen keeps them: older rework and held failures drop out."""
    groups: dict[Signature, list[tuple[int, Lesson]]] = defaultdict(list)
    for position, lesson in enumerate(lessons):
        groups[lesson.pain_point.signature].append((position, lesson))
    kept = [
        pair for signature, group in groups.items() for pair in _still_kept(signature, group, rules)
    ]
    return [lesson for _, lesson in sorted(kept, key=lambda pair: pair[0])]


def _still_kept(
    signature: Signature, group: list[tuple[int, Lesson]], rules: ScreenRules
) -> list[tuple[int, Lesson]]:
    if signature.signal is Signal.REWORKED_EDIT:
        return []
    if signature.signal is not Signal.FAILED_COMMAND:
        return group
    if _failed_command_reason(signature, [lesson for _, lesson in group], rules) is not None:
        return []
    return [(position, lesson) for position, lesson in group if lesson.fix is not None]


def hold_reason(
    signature: Signature, group: Sequence[Lesson], rules: ScreenRules
) -> HoldReason | None:
    """The first reason to hold the group back, or None when it is lesson-grade.

    The developer's ignored patterns are not a reason here: `screen` counts them separately.
    """
    if signature.signal in EXEMPT_SIGNALS:
        return None
    if signature.signal is Signal.FAILED_COMMAND:
        return _failed_command_reason(signature, group, rules)
    return _too_few_sessions(group, rules)


def _failed_command_reason(
    signature: Signature, group: Sequence[Lesson], rules: ScreenRules
) -> HoldReason | None:
    """A failed command needs a shown fix, a message, a lasting target, and to not be a probe.

    Sessions are counted over the occurrences that show the fix: a lesson promises a fix that
    came back, not a failure that came back once fixed and otherwise not.
    """
    fixed = _taught(signature, group)
    if not fixed:
        return HoldReason.NO_FIX_SHOWN
    if is_bare_exit(signature.key[-1]):
        return HoldReason.NO_MESSAGE
    if signature.key[0] in PROBES:
        return HoldReason.PROBE_COMMAND
    if signature.key[1] == INLINE_TARGET or all(lesson.target_created for lesson in fixed):
        return HoldReason.THROWAWAY_SCRIPT
    return _too_few_sessions(fixed, rules)


def _taught(signature: Signature, group: Sequence[Lesson]) -> list[Lesson]:
    """The occurrences a lesson is made of: for a failed command only those that show the fix."""
    if signature.signal is not Signal.FAILED_COMMAND:
        return list(group)
    return [lesson for lesson in group if lesson.fix is not None]


def _too_few_sessions(group: Sequence[Lesson], rules: ScreenRules) -> HoldReason | None:
    """TOO_FEW_SESSIONS when the group is seen in fewer sessions than the rules ask."""
    sessions = {lesson.pain_point.session_id for lesson in group}
    return HoldReason.TOO_FEW_SESSIONS if len(sessions) < rules.min_sessions else None
