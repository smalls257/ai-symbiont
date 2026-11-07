"""Incidents: one plain-language card per mined occurrence, and the trigger a group implies.

Why this exists: a card that reads like miner internals ("failed with exit 4") tells the developer
nothing, and asking them to write triggers is work symbiont can do from what it watched.
Pure over lessons and the session records passed in; failed commands and corrections only.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from symbiont.miner import incident_words as words
from symbiont.miner.codebase import repo_relative
from symbiont.miner.commands import normalise_command, program_words
from symbiont.miner.correction_episode import episode_of
from symbiont.miner.failure_keys import INTERRUPTS, is_interrupt
from symbiont.miner.failure_signature import failure_detail
from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.miner.resolutions import NOTHING_CHANGED, ONLY_UNRELATED_CHANGED, PASSED_RESPELLED
from symbiont.miner.screen import INLINE_TARGET, PROBES
from symbiont.records.schema import Kind, Record

# A trigger needs most of a group's occurrences to agree; 0.6 is "clearly more than a coin flip"
# and was chosen by hand, not tuned [hypothesis].
TRIGGER_SHARE = 0.6
# Steps worth warning about before they happen: they are hard to take back.
BEFORE_STEPS = frozenset({"git push", "git commit", "git merge", "git rebase", "npm publish"})
_EDITED_FILE = re.compile(r"edited `([^`]+)`")
_RAN_COMMAND = re.compile(r"ran `([^`]+)`")
_RETRIES = (NOTHING_CHANGED, PASSED_RESPELLED)
NO_SITUATION = ("", "", "")


class NoiseReason(StrEnum):
    """Why an incident is not worth a look."""

    LOOK_AROUND = "look_around"  # a probe program failed
    INTERRUPT = "interrupt"
    THROWAWAY_SCRIPT = "throwaway_script"
    DELIBERATE_REPRO = (
        "deliberate_repro"  # a throwaway script failed, the code was edited, it passed
    )
    PLAIN_RETRY = "plain_retry"  # passed when run again with nothing changed
    EMPTY_CORRECTION = "empty_correction"


class Outcome(StrEnum):
    """How an incident ended."""

    FIXED_IN_CODE = "fixed_in_code"
    CORRECTED_COMMAND = "corrected_command"
    PASSED_ON_RETRY = "passed_on_retry"
    NEVER_FIXED = "never_fixed"
    DEVELOPER_STEPPED_IN = "developer_stepped_in"  # a correction


class TriggerKind(StrEnum):
    """When the agent should hear a lesson."""

    RUNNING = "running"  # about to run a program, optionally on a path
    EDITING = "editing"  # about to edit files under a path
    BEFORE = "before"  # about to do a named step: "before git push"


@dataclass(frozen=True)
class Incident:
    """One occurrence, told in plain language."""

    session_id: str
    step: int
    signal: Signal
    what_happened: str  # one sentence
    first_wrong: str  # corrections: the agent's first upstream action that went wrong; "" if none
    cost_steps: int  # corrections: agent actions from first_wrong to the correction
    what_fixed_it: str  # one sentence
    outcome: Outcome
    noise: NoiseReason | None  # None means worth a look
    topic: str  # the session's topic name; "" before topics exist
    files: tuple[str, ...]
    # (kind, program, path) of the action it is about: the failed command, or first_wrong.
    situation: tuple[str, str, str]


@dataclass(frozen=True)
class Trigger:
    """The situation a group of incidents shares."""

    kind: TriggerKind
    program: str  # "" for EDITING
    path: str  # the common directory; "" when the occurrences share none
    words: str  # the plain phrase shown and spoken


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
        return _correction_card(lesson, records, topic, repo_names)
    return None


def _failure_card(
    lesson: Lesson, records: Sequence[Record], topic: str, repo_names: frozenset[str]
) -> Incident:
    pain = lesson.pain_point
    program, target, broke = pain.signature.key
    failed = _record_at(records, pain.step)
    detail = failure_detail(failed.raw) if failed is not None else ""
    outcome = _failure_outcome(lesson)
    return Incident(
        session_id=pain.session_id,
        step=pain.step,
        signal=Signal.FAILED_COMMAND,
        what_happened=words.failure_sentence(program, target, broke, detail),
        first_wrong="",
        cost_steps=0,
        what_fixed_it=_failure_fix(lesson, outcome),
        outcome=outcome,
        noise=_failure_noise(lesson, failed),
        topic=topic,
        files=lesson.files,
        situation=(TriggerKind.RUNNING.value, program, _path_of(target, repo_names)),
    )


def _failure_noise(lesson: Lesson, failed: Record | None) -> NoiseReason | None:
    """The verdict, in order: interrupt, look-around, deliberate repro, throwaway, plain retry."""
    program, target, _ = lesson.pain_point.signature.key
    if program in INTERRUPTS or (failed is not None and is_interrupt(failed)):
        return NoiseReason.INTERRUPT
    if program in PROBES:
        return NoiseReason.LOOK_AROUND
    if lesson.target_created and lesson.fix is FixKind.CODE_FIX:
        return NoiseReason.DELIBERATE_REPRO
    if lesson.target_created or target == INLINE_TARGET:
        return NoiseReason.THROWAWAY_SCRIPT
    return NoiseReason.PLAIN_RETRY if lesson.unresolved_because in _RETRIES else None


def _failure_outcome(lesson: Lesson) -> Outcome:
    if lesson.fix is FixKind.CODE_FIX:
        return Outcome.FIXED_IN_CODE
    if lesson.fix is FixKind.CORRECTED_COMMAND:
        return Outcome.CORRECTED_COMMAND
    if lesson.resolution or lesson.unresolved_because in (*_RETRIES, ONLY_UNRELATED_CHANGED):
        return Outcome.PASSED_ON_RETRY
    return Outcome.NEVER_FIXED


def _failure_fix(lesson: Lesson, outcome: Outcome) -> str:
    if outcome is Outcome.FIXED_IN_CODE:
        path = _edited_path(lesson)
        return words.edited_then_passed(path, script=lesson.target_created)
    if outcome is Outcome.CORRECTED_COMMAND:
        return words.corrected_command_sentence(_ran_command(lesson))
    if lesson.resolution:
        return words.passed_later_sentence(", then ".join(lesson.resolution))
    return words.unresolved_sentence(lesson.unresolved_because)


def _edited_path(lesson: Lesson) -> str:
    """The file the fix edited, read from the resolution's own words, else the first file."""
    for step in lesson.resolution:
        if match := _EDITED_FILE.match(step):
            return match.group(1)
    return lesson.files[0] if lesson.files else "the code"


def _ran_command(lesson: Lesson) -> str:
    for step in reversed(lesson.resolution):
        if match := _RAN_COMMAND.match(step):
            return match.group(1)
    return lesson.resolution[-1] if lesson.resolution else "the command"


def _correction_card(
    lesson: Lesson, records: Sequence[Record], topic: str, repo_names: frozenset[str]
) -> Incident:
    pain = lesson.pain_point
    turn = _record_at(records, pain.step)
    text = turn.raw if turn is not None else lesson.quote
    empty = words.is_empty_correction(text)
    common = dict(
        session_id=pain.session_id, step=pain.step, signal=Signal.CORRECTION,
        what_happened=words.correction_sentence(text), outcome=Outcome.DEVELOPER_STEPPED_IN,
        noise=NoiseReason.EMPTY_CORRECTION if empty else None, topic=topic, files=lesson.files,
    )  # fmt: skip
    if turn is None or empty:
        return Incident(first_wrong="", cost_steps=0, what_fixed_it=words.next_edit_sentence(None),
                        situation=NO_SITUATION, **common)  # fmt: skip
    episode = episode_of(turn, records)
    return Incident(
        first_wrong=_first_wrong_words(episode.first_wrong),
        cost_steps=episode.cost_steps,
        what_fixed_it=words.next_edit_sentence(_first_file(episode.next_edit)),
        situation=_situation_of(episode.first_wrong, repo_names),
        **common,
    )


def _first_wrong_words(action: Record | None) -> str:
    if action is None:
        return ""
    if action.kind is Kind.EDIT:
        return words.edit_sentence(_first_file(action) or "")
    failed = action.exit_code not in (None, 0)
    return words.ran_sentence(action.command or "", failed=failed)


def _situation_of(action: Record | None, repo_names: frozenset[str]) -> tuple[str, str, str]:
    """(kind, program, path) of an action: an edit, a hard-to-undo step, or a program run."""
    if action is None:
        return NO_SITUATION
    if action.kind is Kind.EDIT:
        return (TriggerKind.EDITING.value, "", _path_of(_first_file(action) or "", repo_names))
    program, target = normalise_command(action.command or "")
    step = _step_of(action.command or "", program)
    if step in BEFORE_STEPS:
        return (TriggerKind.BEFORE.value, step, "")
    return (TriggerKind.RUNNING.value, program, _path_of(target, repo_names))


def _step_of(command: str, program: str) -> str:
    """`program subcommand` when the first argument is a bare word, else the program."""
    args = program_words(command)[1]
    first = next((arg for arg in args if not arg.startswith("-")), "")
    return f"{program} {first}" if re.fullmatch(r"[a-z][a-z-]*", first) else program


def _path_of(target: str, repo_names: frozenset[str]) -> str:
    """A target as a repo-relative path; "" when there is none."""
    if target in ("", "-", INLINE_TARGET):
        return ""
    return repo_relative(target, repo_names) or target.removeprefix("./")


def _first_file(record: Record | None) -> str | None:
    return record.files[0] if record is not None and record.files else None


def _record_at(records: Sequence[Record], step: int) -> Record | None:
    return next((r for r in records if r.step == step), None)
