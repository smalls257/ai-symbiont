"""Notes: a Decision rendered as plain sentences for the agent to read."""

from collections.abc import Callable, Collection
from enum import StrEnum

from symbiont.core.slot import Decision
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
) -> list[str]:
    """Up to `max_notes` sentences across the chosen kinds, in NoteKind order."""
    notes = [note for kind in NoteKind if kind in kinds for note in _BY_KIND[kind](decision)]
    return [note for note in notes if note][:max_notes]


def _recalls(decision: Decision) -> list[str]:
    return [_recalled(record) for record in decision.recall]


def _warning(decision: Decision) -> list[str]:
    if decision.trouble is None:
        return []
    return [_TEMPLATES[decision.trouble.signal](decision.trouble, len(decision.why))]


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def _failed_command(signature: Signature, count: int) -> str:
    *target, error = signature.key
    command = " ".join(part for part in target if part != NO_PATH)
    broke = "a non-zero exit" if error.startswith("exit ") else error
    return f"This command has failed {_times(count)} before: `{command}` -> {broke}."


def _reworked_edit(signature: Signature, count: int) -> str:
    return f"You have redone your edits to `{signature.key[0]}` {_times(count)} before."


def _review_flag(signature: Signature, count: int) -> str:
    return f"A reviewer flagged `{signature.key[0]}` {_times(count)} before."


def _correction(signature: Signature, count: int) -> str:
    path, words = signature.key
    where = "" if path == NO_PATH else f" about `{path}`"
    return f"You were corrected{where} {_times(count)} before, on: {words}."


def _loop(signature: Signature, count: int) -> str:
    kind, target = signature.key[0], signature.key[1]
    what = f"the command `{target}`" if kind == "command" else f"`{target}`"
    return f"You went in circles over {what} in an earlier session ({_times(count)})."


def _blast_radius(signature: Signature, count: int) -> str:
    edited, dependent = signature.key
    return (
        f"You edited `{edited}` before without touching `{dependent}`, "
        "and the tests that cover it broke."
    )


def _recalled(record: Record) -> str:
    if record.command:
        return f"Earlier in this project you ran `{record.command}`."
    if record.files:
        return f"Earlier in this project you worked on `{record.files[0]}`."
    return ""


_TEMPLATES: dict[Signal, Callable[[Signature, int], str]] = {
    Signal.FAILED_COMMAND: _failed_command,
    Signal.REWORKED_EDIT: _reworked_edit,
    Signal.REVIEW_FLAG: _review_flag,
    Signal.CORRECTION: _correction,
    Signal.LOOP: _loop,
    Signal.BLAST_RADIUS: _blast_radius,
}

_BY_KIND: dict[NoteKind, Callable[[Decision], list[str]]] = {
    NoteKind.WARN: _warning,
    NoteKind.RECALL: _recalls,
}
