"""Incidents: one plain-language card per mined occurrence, and the trigger a group implies.

Why this exists: a card that reads like miner internals ("failed with exit 4") tells the developer
nothing, and asking them to write triggers is work symbiont can do from what it watched.
Pure over lessons and the session records passed in; failed commands and corrections only.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from symbiont.miner import incident_words as words
from symbiont.miner.commands import command_stages, program_words
from symbiont.miner.complaint_line import complaint_of
from symbiont.miner.environment_fix import setup_command
from symbiont.miner.failure_keys import INTERRUPTS, is_interrupt
from symbiont.miner.failure_signature import failure_detail
from symbiont.miner.fix_words import edit_clause, resolution_phrase
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
from symbiont.miner.read_only import is_read_only
from symbiont.miner.resolutions import (
    NOTHING_CHANGED,
    ONLY_UNRELATED_CHANGED,
    PASSED_RESPELLED,
    later_success_of,
    subcommand_of,
)
from symbiont.miner.screen import INLINE_TARGET, PROBES
from symbiont.miner.story import story_of
from symbiont.records.schema import Kind, Record

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
_RETRIES = (NOTHING_CHANGED, PASSED_RESPELLED)
# What counts as the agent doing something between a failure and its pass.
_ACTIONS = frozenset({Kind.COMMAND, Kind.EDIT, Kind.READ})


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
        what_fixed_it=_failure_fix(lesson, outcome, setup, failed, repo_names),
        outcome=outcome,
        noise=_failure_noise(lesson, failed, outcome, records),
        topic=topic,
        files=lesson.files,
        situation=(TriggerKind.RUNNING.value, program, path_of(target, repo_names)),
        fingerprint=f"failure:{program}:{broke}",
        example=words.command_example(failed.command if failed is not None else None, repo_names),
        **_story_fields(
            lesson, repo_names, setup if outcome is Outcome.ENVIRONMENT_FIXED else None
        ),
    )


def _story_fields(lesson: Lesson, repo_names: frozenset[str], setup: str | None) -> dict[str, str]:
    """The card's story lines; the setup command is named only when the miner found one."""
    story = story_of(lesson, "", repo_names, setup)
    return {"working_on": story.working_on, "broke": story.broke, "ended": story.ended}


def _failure_noise(
    lesson: Lesson, failed: Record | None, outcome: Outcome, records: Sequence[Record]
) -> NoiseReason | None:
    """The verdict, in order: interrupt, look-around, repro, throwaway, fixed right away, retry."""
    return _noise_in_what_ran(lesson, failed) or _noise_in_how_it_ended(
        lesson, failed, outcome, records
    )


def _noise_in_what_ran(lesson: Lesson, failed: Record | None) -> NoiseReason | None:
    program, target, _ = lesson.pain_point.signature.key
    if _interrupted(program, failed):
        return NoiseReason.INTERRUPT
    if program in PROBES:
        return NoiseReason.LOOK_AROUND
    if lesson.target_created and lesson.fix is FixKind.CODE_FIX:
        return NoiseReason.DELIBERATE_REPRO
    if lesson.target_created or target == INLINE_TARGET:
        return NoiseReason.THROWAWAY_SCRIPT
    return None


def _noise_in_how_it_ended(
    lesson: Lesson, failed: Record | None, outcome: Outcome, records: Sequence[Record]
) -> NoiseReason | None:
    if outcome is not Outcome.FIXED_IN_CODE and failed and _fixed_right_away(failed, records):
        return NoiseReason.FIXED_RIGHT_AWAY
    retried = lesson.unresolved_because in _RETRIES and outcome is not Outcome.ENVIRONMENT_FIXED
    return NoiseReason.PLAIN_RETRY if retried else None


def _fixed_right_away(failed: Record, records: Sequence[Record]) -> bool:
    """The agent's first step fixed it: alone before the pass, the setup, or chained into the pass.

    Asked only of fixes that left the code alone: a one-edit code fix may carry what the code needs.
    A first step counts even when the retry then broke some other way, never when it did not take.
    """
    success = later_success_of(failed, records)
    if success is None:
        return False
    between = [r for r in records if failed.step < r.step < success.step and r.kind in _ACTIONS]
    if not between:
        return len(command_stages(success.command or "")) > 1
    if not _changed_something(between[0]):
        return False
    return len(between) == 1 or _retried_past_it(failed, between[1:])


def _retried_past_it(failed: Record, after: Sequence[Record]) -> bool:
    """The next try of the same command no longer printed the failure's error line."""
    wanted = _program_of(failed.command or "")
    retry = next(
        (r for r in after if r.kind is Kind.COMMAND and _program_of(r.command or "") == wanted),
        None,
    )
    error = _error_line(failed.raw)
    return retry is not None and bool(error) and _error_line(retry.raw) != error


def _error_line(output: str) -> str:
    return complaint_of(output) or failure_detail(output)


def _program_of(command: str) -> tuple[str, str]:
    return (program_words(command)[0], subcommand_of(command))


def _changed_something(action: Record) -> bool:
    """A step that worked and changed things: a look-around or a failed install fixed nothing."""
    if action.exit_code not in (0, None):
        return False
    return action.kind is Kind.EDIT or (
        action.kind is Kind.COMMAND and not is_read_only(action.command or "")
    )


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


def _failure_fix(
    lesson: Lesson,
    outcome: Outcome,
    setup: str | None,
    failed: Record | None,
    repo_names: frozenset[str],
) -> str:
    if outcome is Outcome.FIXED_IN_CODE:
        return words.edited_then_passed(_edited_names(lesson), script=lesson.target_created)
    if outcome is Outcome.ENVIRONMENT_FIXED and setup is not None:
        return words.setup_sentence(setup, repo_names)
    if outcome is Outcome.CORRECTED_COMMAND:
        return words.corrected_command_sentence(_ran_command(lesson, failed))
    if lesson.resolution:
        return words.passed_later_sentence(resolution_phrase(lesson.resolution))
    return words.unresolved_sentence(lesson.unresolved_because)


def _edited_names(lesson: Lesson) -> str:
    """The file names the fix edited, as the fix phrase says them, else the first file's name."""
    for phrase in lesson.resolution:
        if named := edit_clause(phrase):
            return named
    return PurePosixPath(lesson.files[0]).name if lesson.files else "the code"


def _ran_command(lesson: Lesson, failed: Record | None) -> str:
    """The last command the resolution ran that is not the failed command itself."""
    own = failed.command if failed is not None else None
    for command in reversed(lesson.fix_commands):
        if command != own:
            return command
    return lesson.fix_commands[-1] if lesson.fix_commands else "the command"
