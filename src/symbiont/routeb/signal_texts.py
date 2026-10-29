"""Route B wording per signal: the question, answer and correction for each kind of trouble.

Split from `dataset` so that one place decides *what is quoted and how it is phrased* and the
other decides *which pain points become examples*. Every answer and target is a verbatim quote of
the original records (`quote_record`), never a paraphrase: a summary would teach the model our
words, not what happened. Pure: records in, text out.
"""

from collections.abc import Callable, Sequence

from symbiont.miner.painpoint import PainPoint, Signal
from symbiont.miner.resolutions import Resolution, is_action, reason_of, resolution_of
from symbiont.records.schema import Kind, Record

_OMITTED = "[...]\n"

Quote = Callable[[Record], str]
Correction = tuple[str, str, list[Record]]  # (situation, target, records used)
NoCorrection = str  # the reason the history holds no correction
RecallText = Callable[[PainPoint, list[Record], Quote], tuple[str, str]]
CorrectionText = Callable[
    [PainPoint, list[Record], Sequence[Record], Quote], Correction | NoCorrection
]


# --- quoting ---------------------------------------------------------------------


def _clip_keeping_end(text: str, limit: int) -> str:
    """A verbatim slice that keeps the end of command output, where the error is."""
    return text if len(text) <= limit else _OMITTED + text[-limit:]


def _clip_keeping_start(text: str, limit: int) -> str:
    """A verbatim slice that keeps the start of diffs and prose."""
    return text if len(text) <= limit else text[:limit] + "\n" + _OMITTED.strip()


def quote_record(record: Record, limit: int) -> str:
    """The record's original text as a training quote, clipped to `limit` characters per part."""
    if record.kind in (Kind.COMMAND, Kind.TEST_RESULT):
        return f"$ {record.command or ''}\n{_clip_keeping_end(record.raw, limit)}"
    if record.kind == Kind.EDIT:
        files = ", ".join(record.files)
        return f"{files}\n{_clip_keeping_start(record.diff or record.raw, limit)}"
    if record.kind == Kind.REVIEW_COMMENT:
        comment = _clip_keeping_start(record.raw, limit)
        return f"{comment}\n{_clip_keeping_start(record.diff or '', limit)}"
    return _clip_keeping_start(record.raw, limit)


# --- recall: question and answer per signal --------------------------------------


def _recall_failed_command(pain: PainPoint, cited: list[Record], quote: Quote) -> tuple[str, str]:
    """Question and answer for a failed command."""
    (failed,) = cited
    return f"What broke last time I ran `{failed.command}`?", quote(failed)


def _recall_reworked_edit(pain: PainPoint, cited: list[Record], quote: Quote) -> tuple[str, str]:
    """Question and answer for a reworked edit."""
    path = pain.signature.key[0]
    first, last = cited[0], cited[-1]
    return (
        f"What did I have to redo in {path}?",
        f"I first wrote:\n{quote(first)}\nThen I replaced it with:\n{quote(last)}",
    )


def _recall_review_flag(pain: PainPoint, cited: list[Record], quote: Quote) -> tuple[str, str]:
    """Question and answer for a review flag."""
    return f"What did the reviewer flag in {pain.signature.key[0]}?", quote(cited[0])


def _recall_correction(pain: PainPoint, cited: list[Record], quote: Quote) -> tuple[str, str]:
    """Question and answer for a user correction."""
    path = pain.signature.key[0]
    where = "last time" if path == "-" else f"in {path}"
    return f"What did I correct you on {where}?", quote(cited[0])


def _recall_loop(pain: PainPoint, cited: list[Record], quote: Quote) -> tuple[str, str]:
    """Question and answer for a loop."""
    return (
        "Where did I get stuck going round in circles?",
        f"{len(cited)} times in a row:\n{quote(cited[0])}",
    )


def _recall_blast_radius(pain: PainPoint, cited: list[Record], quote: Quote) -> tuple[str, str]:
    """Question and answer for a broken dependent."""
    path, dependent = pain.signature.key
    edit, failure = cited
    return (
        f"What broke last time I edited {path}?",
        f"After this change:\n{quote(edit)}\nthis run failed, in or around {dependent}, "
        f"which I had not looked at:\n{quote(failure)}",
    )


RECALL_BY_SIGNAL: dict[Signal, RecallText] = {
    Signal.FAILED_COMMAND: _recall_failed_command,
    Signal.REWORKED_EDIT: _recall_reworked_edit,
    Signal.REVIEW_FLAG: _recall_review_flag,
    Signal.CORRECTION: _recall_correction,
    Signal.LOOP: _recall_loop,
    Signal.BLAST_RADIUS: _recall_blast_radius,
}


# --- correction: (situation, target, records used) or the reason there is none ---


def _fix_failed_command(
    pain: PainPoint, cited: list[Record], records: Sequence[Record], quote: Quote
) -> Correction | NoCorrection:
    """The target is what changed between the failure and the pass, then the passing run."""
    (failed,) = cited
    found = resolution_of(pain, cited, records)
    if not isinstance(found, Resolution):
        return reason_of(found) or ""
    return (
        f"This command failed:\n{quote(failed)}\nWhat should I run instead?",
        "\n".join(_action_text(step) for step in found.steps),
        [failed, *found.steps],
    )


def _fix_correction(
    pain: PainPoint, cited: list[Record], records: Sequence[Record], quote: Quote
) -> Correction | NoCorrection:
    """The correction target after a user correction, or why there is none."""
    (turn,) = cited
    found = resolution_of(pain, cited, records)
    if not isinstance(found, Resolution):
        return reason_of(found) or ""
    (action,) = found.steps
    corrected = _last_action_before(turn, records)
    before = f"What I was doing:\n{quote(corrected)}\n" if corrected else ""
    situation = f"{before}The developer said:\n{quote(turn)}\nWhat should I do next?"
    return situation, _action_text(action), [r for r in (corrected, turn, action) if r is not None]


def _last_action_before(turn: Record, records: Sequence[Record]) -> Record | None:
    """The last action in the turn's session before it, or None."""
    earlier = [r for r in records if r.session_id == turn.session_id and r.step < turn.step]
    return next((r for r in reversed(earlier) if is_action(r)), None)


def _fix_reworked_edit(
    pain: PainPoint, cited: list[Record], records: Sequence[Record], quote: Quote
) -> Correction | NoCorrection:
    """The correction target for a reworked edit."""
    path = pain.signature.key[0]
    found = resolution_of(pain, cited, records)
    if not isinstance(found, Resolution):
        return reason_of(found) or ""
    *discarded, _ = cited
    (survivor,) = found.steps
    return (
        f"This edit to {path} was later redone:\n{quote(discarded[0])}\nWhat should the edit be?",
        _action_text(survivor),
        [*discarded, survivor],
    )


def _fix_blast_radius(
    pain: PainPoint, cited: list[Record], records: Sequence[Record], quote: Quote
) -> Correction | NoCorrection:
    """The correction target for a broken dependent."""
    path, dependent = pain.signature.key
    edit, failure = cited
    return (
        f"I changed this:\n{quote(edit)}\nand then this failed:\n{quote(failure)}\n"
        "What should I have looked at before changing it?",
        f"Read {dependent} before changing {path}.",
        [edit, failure],
    )


def _fix_review_flag(
    pain: PainPoint, cited: list[Record], records: Sequence[Record], quote: Quote
) -> Correction | NoCorrection:
    """The correction target for a review flag."""
    comment, answer = cited
    return (
        f"A reviewer flagged this:\n{quote(comment)}\nWhat should the change be?",
        _action_text(answer),
        [comment, answer],
    )


def _no_fix_in_loop(
    pain: PainPoint, cited: list[Record], records: Sequence[Record], quote: Quote
) -> Correction | NoCorrection:
    """A loop has no correction source: always a stated reason."""
    return "a loop has no correction source: nothing in the history says what to do instead"


CORRECTION_BY_SIGNAL: dict[Signal, CorrectionText] = {
    Signal.FAILED_COMMAND: _fix_failed_command,
    Signal.CORRECTION: _fix_correction,
    Signal.REWORKED_EDIT: _fix_reworked_edit,
    Signal.BLAST_RADIUS: _fix_blast_radius,
    Signal.REVIEW_FLAG: _fix_review_flag,
    Signal.LOOP: _no_fix_in_loop,
}


# --- what the agent did, in the records ------------------------------------------


def _action_text(record: Record) -> str:
    """An action as text: the command, or the files and diff."""
    if record.kind == Kind.COMMAND:
        return record.command or ""
    return f"{', '.join(record.files)}\n{record.diff}"
