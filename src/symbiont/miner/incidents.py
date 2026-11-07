"""Incidents: one plain-language card per mined occurrence, and the trigger a group implies.

Why this exists: a card that reads like miner internals ("failed with exit 4") tells the developer
nothing, and asking them to write triggers is work symbiont can do from what it watched.
Pure over lessons and the session records passed in; failed commands and corrections only.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from symbiont.miner import incident_words as words
from symbiont.miner.environment_fix import setup_command
from symbiont.miner.failure_keys import INTERRUPTS, is_interrupt
from symbiont.miner.failure_signature import failure_detail
from symbiont.miner.fixes import FixKind
from symbiont.miner.incident_corrections import correction_card, path_of, record_at
from symbiont.miner.incident_types import (
    Incident,
    NoiseReason,
    Outcome,
    Trigger,
    TriggerKind,
)
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.miner.resolutions import NOTHING_CHANGED, ONLY_UNRELATED_CHANGED, PASSED_RESPELLED
from symbiont.miner.screen import INLINE_TARGET, PROBES
from symbiont.records.schema import Record

__all__ = [
    "Incident",
    "NoiseReason",
    "Outcome",
    "Trigger",
    "TriggerKind",
    "incidents_from",
    "noise_words",
    "trigger_of",
]

# A trigger needs most of a group's occurrences to agree; 0.6 is "clearly more than a coin flip"
# and was chosen by hand, not tuned [hypothesis].
TRIGGER_SHARE = 0.6
_EDITED_FILE = re.compile(r"edited `([^`]+)`")
_RAN_COMMAND = re.compile(r"ran `([^`]+)`")
_RETRIES = (NOTHING_CHANGED, PASSED_RESPELLED)


def noise_words(reason: NoiseReason) -> str:
    """The reason as a phrase for the card."""
    return words.NOISE_PHRASES[reason.value]


def incidents_from(
    lessons: Sequence[Lesson],
    topics: Mapping[str, str],
    sessions: Mapping[str, Sequence[Record]],
    repo_names: frozenset[str] = frozenset(),
) -> list[Incident]:
    """A card per failed command or correction; other signals are not cards and are skipped."""
    made = [_incident(lesson, topics, sessions, repo_names) for lesson in lessons]
    return [incident for incident in made if incident is not None]


def trigger_of(incidents: Sequence[Incident]) -> Trigger | None:
    """The majority situation when it covers TRIGGER_SHARE of the occurrences, else None."""
    counted = Counter(
        (kind, program) for kind, program, _ in (i.situation for i in incidents) if kind
    )
    if not counted:
        return None
    (kind, program), count = counted.most_common(1)[0]
    if count / len(incidents) < TRIGGER_SHARE:
        return None
    paths = [path for k, p, path in (i.situation for i in incidents) if (k, p) == (kind, program)]
    path = "" if kind == TriggerKind.BEFORE else _common_directory(paths)
    return Trigger(TriggerKind(kind), program, path, words.trigger_phrase(kind, program, path))


def _common_directory(paths: Sequence[str]) -> str:
    """The longest directory prefix every path shares; a file's own name is not part of it."""
    split = [_directory(path).split("/") if _directory(path) else [] for path in paths]
    shared: list[str] = []
    for level in zip(*split, strict=False):
        if len(set(level)) != 1:
            break
        shared.append(level[0])
    return "/".join(shared)


def _directory(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if parts and "." in parts[-1]:
        parts = parts[:-1]
    return "/".join(parts)


def _incident(
    lesson: Lesson,
    topics: Mapping[str, str],
    sessions: Mapping[str, Sequence[Record]],
    repo_names: frozenset[str],
) -> Incident | None:
    signal = lesson.pain_point.signature.signal
    session_id = lesson.pain_point.session_id
    records = sessions.get(session_id, ())
    topic = topics.get(session_id, "")
    if signal is Signal.FAILED_COMMAND:
        return _failure_card(lesson, records, topic, repo_names)
    if signal is Signal.CORRECTION:
        return correction_card(lesson, records, topic, repo_names)
    return None


def _failure_card(
    lesson: Lesson, records: Sequence[Record], topic: str, repo_names: frozenset[str]
) -> Incident:
    pain = lesson.pain_point
    program, target, broke = pain.signature.key
    failed = record_at(records, pain.step)
    setup = setup_command(failed, records) if failed is not None else None
    detail = failure_detail(failed.raw) if failed is not None else ""
    outcome = _failure_outcome(lesson, setup)
    return Incident(
        session_id=pain.session_id,
        step=pain.step,
        signal=Signal.FAILED_COMMAND,
        what_happened=words.failure_sentence(program, target, broke, detail),
        first_wrong="",
        cost_steps=0,
        what_fixed_it=_failure_fix(lesson, outcome, setup, failed),
        outcome=outcome,
        noise=_failure_noise(lesson, failed, outcome),
        topic=topic,
        files=lesson.files,
        situation=(TriggerKind.RUNNING.value, program, path_of(target, repo_names)),
    )


def _failure_noise(lesson: Lesson, failed: Record | None, outcome: Outcome) -> NoiseReason | None:
    """The verdict, in order: interrupt, look-around, deliberate repro, throwaway, plain retry."""
    program, target, _ = lesson.pain_point.signature.key
    if _interrupted(program, failed):
        return NoiseReason.INTERRUPT
    if program in PROBES:
        return NoiseReason.LOOK_AROUND
    if lesson.target_created and lesson.fix is FixKind.CODE_FIX:
        return NoiseReason.DELIBERATE_REPRO
    if lesson.target_created or target == INLINE_TARGET:
        return NoiseReason.THROWAWAY_SCRIPT
    retried = lesson.unresolved_because in _RETRIES and outcome is not Outcome.ENVIRONMENT_FIXED
    return NoiseReason.PLAIN_RETRY if retried else None


def _interrupted(program: str, failed: Record | None) -> bool:
    return program in INTERRUPTS or (failed is not None and is_interrupt(failed))


def _failure_outcome(lesson: Lesson, setup: str | None) -> Outcome:
    if lesson.fix is FixKind.CODE_FIX:
        return Outcome.FIXED_IN_CODE
    if setup is not None:
        return Outcome.ENVIRONMENT_FIXED
    if lesson.fix is FixKind.CORRECTED_COMMAND:
        return Outcome.CORRECTED_COMMAND
    if lesson.resolution or lesson.unresolved_because in (*_RETRIES, ONLY_UNRELATED_CHANGED):
        return Outcome.PASSED_ON_RETRY
    return Outcome.NEVER_FIXED


def _failure_fix(lesson: Lesson, outcome: Outcome, setup: str | None, failed: Record | None) -> str:
    if outcome is Outcome.FIXED_IN_CODE:
        return words.edited_then_passed(_edited_path(lesson), script=lesson.target_created)
    if outcome is Outcome.ENVIRONMENT_FIXED and setup is not None:
        return words.setup_sentence(setup)
    if outcome is Outcome.CORRECTED_COMMAND:
        return words.corrected_command_sentence(_ran_command(lesson, failed))
    if lesson.resolution:
        return words.passed_later_sentence(", then ".join(lesson.resolution))
    return words.unresolved_sentence(lesson.unresolved_because)


def _edited_path(lesson: Lesson) -> str:
    """The file the fix edited, read from the resolution's own words, else the first file."""
    for step in lesson.resolution:
        if match := _EDITED_FILE.match(step):
            return match.group(1)
    return lesson.files[0] if lesson.files else "the code"


def _ran_command(lesson: Lesson, failed: Record | None) -> str:
    """The last command the resolution ran that is not the failed command itself."""
    own = failed.command if failed is not None else None
    for step in reversed(lesson.resolution):
        match = _RAN_COMMAND.match(step)
        if match and match.group(1) != own:
            return match.group(1)
    return lesson.resolution[-1] if lesson.resolution else "the command"
