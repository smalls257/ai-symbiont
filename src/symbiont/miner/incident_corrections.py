"""The card of a developer correction, and the situation of the action it is about."""

import re
from collections.abc import Sequence

from symbiont.miner import incident_words as words
from symbiont.miner.codebase import repo_relative
from symbiont.miner.commands import normalise_command, program_words
from symbiont.miner.correction_episode import NO_EPISODE, episode_of
from symbiont.miner.empty_correction import is_empty_correction
from symbiont.miner.incident_types import (
    NO_SITUATION,
    Incident,
    NoiseReason,
    Outcome,
    TriggerKind,
)
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.miner.resolutions import bare_arguments
from symbiont.miner.screen import INLINE_TARGET
from symbiont.records.schema import Kind, Record

# Steps worth warning about before they happen: they are hard to take back.
# What a correction card quotes of the developer: a line, not their whole message.
SAID_CHARS = 120
BEFORE_STEPS = frozenset({"git push", "git commit", "git merge", "git rebase", "npm publish"})


def correction_card(
    lesson: Lesson, records: Sequence[Record], topic: str, repo_names: frozenset[str]
) -> Incident:
    """The card of a correction: what the developer said, where the agent went wrong first."""
    pain = lesson.pain_point
    turn = record_at(records, pain.step)
    text = turn.raw if turn is not None else lesson.quote
    empty = is_empty_correction(text)
    episode = episode_of(turn, records) if turn is not None and not empty else NO_EPISODE
    return Incident(
        session_id=pain.session_id,
        step=pain.step,
        signal=Signal.CORRECTION,
        what_happened=words.correction_sentence(text),
        first_wrong=_first_wrong_words(episode.first_wrong),
        cost_steps=episode.cost_steps,
        what_fixed_it=words.next_edit_sentence(first_file(episode.next_edit)),
        outcome=Outcome.DEVELOPER_STEPPED_IN,
        noise=NoiseReason.EMPTY_CORRECTION if empty else None,
        topic=topic,
        files=lesson.files,
        situation=situation_of(episode.first_wrong, repo_names),
        example=words.quoted_words(text),
        broke="" if empty else _said(text),
        ended=words.next_edit_sentence(first_file(episode.next_edit)),
    )


def _said(text: str) -> str:
    """The developer's own words, one line of at most SAID_CHARS."""
    flat = " ".join(words.quoted_words(text).split())
    return flat if len(flat) <= SAID_CHARS else flat[: SAID_CHARS - 1].rstrip() + "…"


def _first_wrong_words(action: Record | None) -> str:
    if action is None:
        return ""
    if action.kind is Kind.EDIT:
        return words.edit_sentence(first_file(action) or "")
    failed = action.exit_code not in (None, 0)
    return words.ran_sentence(action.command or "", failed=failed)


def situation_of(action: Record | None, repo_names: frozenset[str]) -> tuple[str, str, str]:
    """(kind, program, path) of an action: an edit, a hard-to-undo step, or a program run."""
    if action is None:
        return NO_SITUATION
    if action.kind is Kind.EDIT:
        return (TriggerKind.EDITING.value, "", path_of(first_file(action) or "", repo_names))
    program, target = normalise_command(action.command or "")
    step = _step_of(action.command or "", program)
    if step in BEFORE_STEPS:
        return (TriggerKind.BEFORE.value, step, "")
    return (TriggerKind.RUNNING.value, program, path_of(target, repo_names))


def _step_of(command: str, program: str) -> str:
    """`program subcommand` when the first argument is a bare word, else the program."""
    words = bare_arguments(program_words(command)[1])
    first = words[0] if words else ""
    return f"{program} {first}" if re.fullmatch(r"[a-z][a-z-]*", first) else program


def path_of(target: str, repo_names: frozenset[str]) -> str:
    """A target as a repo-relative path; "" when there is none."""
    if target in ("", "-", INLINE_TARGET):
        return ""
    return repo_relative(target, repo_names) or target.removeprefix("./")


def first_file(record: Record | None) -> str | None:
    """The first file a record touched, or None."""
    return record.files[0] if record is not None and record.files else None


def record_at(records: Sequence[Record], step: int) -> Record | None:
    """The record at `step` in the session, or None."""
    return next((r for r in records if r.step == step), None)
