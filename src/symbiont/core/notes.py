"""Notes: a Decision or a lesson rendered as plain sentences for the agent to read.

A lesson reads as three parts: what happened, how it was resolved, the check to
run. Domain prose only: no scores, feature names or thresholds.
"""

from collections.abc import Callable, Collection, Sequence
from enum import StrEnum

from symbiont.core.slot import Decision
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal, Signature
from symbiont.records.schema import Record

DEFAULT_MAX_NOTES = 2
NO_PATH = "-"


class NoteKind(StrEnum):
    """What a note is for; one more member (with its own templates) adds a kind."""

    WARN = "warn"
    RECALL = "recall"


def render(
    decision: Decision,
    *,
    max_notes: int = DEFAULT_MAX_NOTES,
    kinds: Collection[NoteKind] = tuple(NoteKind),
    lessons: Sequence[Lesson] = (),
) -> list[str]:
    """Up to `max_notes` sentences across the chosen kinds, in NoteKind order.

    A warning backed by one of `lessons` also says how it was resolved and what to check.
    """
    notes = [
        note for kind in NoteKind if kind in kinds for note in _BY_KIND[kind](decision, lessons)
    ]
    return [note for note in notes if note][:max_notes]


def render_lesson(lesson: Lesson) -> str:
    """What happened, how it was resolved, and the check to run, as three sentences."""
    signature = lesson.pain_point.signature
    happened = _HAPPENED[signature.signal](signature)
    return f"What happened: {happened}. {_resolved(lesson)} {_check(signature)}"


def _recalls(decision: Decision, lessons: Sequence[Lesson]) -> list[str]:
    """One sentence per recalled record."""
    return [_recalled(record) for record in decision.recall]


def _warning(decision: Decision, lessons: Sequence[Lesson]) -> list[str]:
    """The warning sentence for the decision's trouble, with the fix when a lesson backs it."""
    if decision.trouble is None:
        return []
    said = _TEMPLATES[decision.trouble.signal](decision.trouble, len(decision.why))
    backing = _backing_lesson(decision, lessons)
    if backing is None:
        return [said]
    return [f"{said} {_resolved(backing)} {_check(decision.trouble)}"]


def _backing_lesson(decision: Decision, lessons: Sequence[Lesson]) -> Lesson | None:
    """The latest lesson behind the warning, preferring one whose fix is known."""
    cited = set(decision.why)
    backing = [lesson for lesson in lessons if lesson.pain_point in cited]
    resolved = [lesson for lesson in backing if lesson.resolution]
    preferred = resolved or backing
    return preferred[-1] if preferred else None


def _resolved(lesson: Lesson) -> str:
    """How a lesson was resolved, and what else changed between the failure and the pass."""
    meanwhile = ""
    if lesson.changed_alongside:
        changed = ", ".join(lesson.changed_alongside)
        meanwhile = f" Between the failure and the pass you also {changed}."
    if not lesson.resolution:
        return "No fix was found in the history." + meanwhile
    return f"Last time it was resolved when you {', then '.join(lesson.resolution)}.{meanwhile}"


def _times(count: int) -> str:
    """`once` or `N times`, for prose."""
    return "once" if count == 1 else f"{count} times"


def _failed_command(signature: Signature, count: int) -> str:
    """Note for a command that failed the same way before."""
    *target, error = signature.key
    command = " ".join(part for part in target if part != NO_PATH)
    broke = "a non-zero exit" if error.startswith("exit ") else error
    return f"This command has failed {_times(count)} before: `{command}` -> {broke}."


def _reworked_edit(signature: Signature, count: int) -> str:
    """Note for a file whose edits were redone before."""
    return f"You have redone your edits to `{signature.key[0]}` {_times(count)} before."


def _review_flag(signature: Signature, count: int) -> str:
    """Note for a file a reviewer flagged before."""
    return f"A reviewer flagged `{signature.key[0]}` {_times(count)} before."


def _correction(signature: Signature, count: int) -> str:
    """Note for an earlier user correction."""
    path, words = signature.key
    where = "" if path == NO_PATH else f" about `{path}`"
    return f"You were corrected{where} {_times(count)} before, on: {words}."


def _loop(signature: Signature, count: int) -> str:
    """Note for an earlier session that went in circles."""
    kind, target = signature.key[0], signature.key[1]
    what = f"the command `{target}`" if kind == "command" else f"`{target}`"
    return f"You went in circles over {what} in an earlier session ({_times(count)})."


def _blast_radius(signature: Signature, count: int) -> str:
    """Note for an edit that broke its dependents' tests before."""
    edited, dependent = signature.key
    return (
        f"You edited `{edited}` before without touching `{dependent}`, "
        "and the tests that cover it broke."
    )


def _recalled(record: Record) -> str:
    """A sentence for one recalled record; empty when it has neither command nor file."""
    if record.command:
        return f"Earlier in this project you ran `{record.command}`."
    if record.files:
        return f"Earlier in this project you worked on `{record.files[0]}`."
    return ""


def _command_of(signature: Signature) -> str:
    """The command text of a command signature."""
    *target, _ = signature.key
    return " ".join(part for part in target if part != NO_PATH)


def _where(path: str) -> str:
    """` about <path>` for a path, empty for none."""
    return "" if path == NO_PATH else f" about `{path}`"


_HAPPENED: dict[Signal, Callable[[Signature], str]] = {
    Signal.FAILED_COMMAND: lambda sig: f"`{_command_of(sig)}` failed with {sig.key[-1]}",
    Signal.REWORKED_EDIT: lambda sig: f"your edits to `{sig.key[0]}` were redone",
    Signal.REVIEW_FLAG: lambda sig: f"a reviewer flagged `{sig.key[0]}`",
    Signal.CORRECTION: lambda sig: f"you were corrected{_where(sig.key[0])} on: {sig.key[1]}",
    Signal.LOOP: lambda sig: f"you went in circles over `{sig.key[1]}`",
    Signal.BLAST_RADIUS: lambda sig: (
        f"editing `{sig.key[0]}` without reading `{sig.key[1]}` broke the tests that cover it"
    ),
}

_CHECKS: dict[Signal, Callable[[Signature], str]] = {
    Signal.FAILED_COMMAND: lambda sig: (
        f"Check: run `{_command_of(sig)}` and confirm it passes before moving on."
    ),
    Signal.REWORKED_EDIT: lambda sig: f"Check: read the current `{sig.key[0]}` before editing it.",
    Signal.REVIEW_FLAG: lambda sig: (
        f"Check: compare `{sig.key[0]}` with the reviewer's comment before submitting."
    ),
    Signal.CORRECTION: lambda sig: "Check: confirm your next step does what the developer asked.",
    Signal.LOOP: lambda sig: "Check: if you are about to repeat it, stop and try another approach.",
    Signal.BLAST_RADIUS: lambda sig: (
        f"Check: read `{sig.key[1]}` and run its tests before changing `{sig.key[0]}`."
    ),
}


def _check(signature: Signature) -> str:
    """The check to run for a signature."""
    return _CHECKS[signature.signal](signature)


_TEMPLATES: dict[Signal, Callable[[Signature, int], str]] = {
    Signal.FAILED_COMMAND: _failed_command,
    Signal.REWORKED_EDIT: _reworked_edit,
    Signal.REVIEW_FLAG: _review_flag,
    Signal.CORRECTION: _correction,
    Signal.LOOP: _loop,
    Signal.BLAST_RADIUS: _blast_radius,
}

_BY_KIND: dict[NoteKind, Callable[[Decision, Sequence[Lesson]], list[str]]] = {
    NoteKind.WARN: _warning,
    NoteKind.RECALL: _recalls,
}
