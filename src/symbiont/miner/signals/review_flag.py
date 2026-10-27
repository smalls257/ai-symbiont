"""Signal: a hunk a reviewer flagged that was later changed.

A review comment record carries the hunk it sits on (`diff`) and its file.
The flag holds when a later applied edit on the same file takes out a line
the hunk added: the comment led to rework. Compared by content, like
reworked edits, because review hunks and later commits number lines
differently. A comment on a hunk that adds nothing is not judged.

Key `(path,)`, placed at the comment, citing the comment and the first
change that answered it.
"""

from collections.abc import Sequence

from symbiont.miner.diffs import added_lines, removed_lines
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.records.schema import Kind, Record


def find_review_flags(records: Sequence[Record]) -> list[PainPoint]:
    """Find review comments whose flagged lines a later edit answered."""
    found = []
    for position, comment in enumerate(records):
        if comment.kind != Kind.REVIEW_COMMENT:
            continue
        flagged = added_lines(comment.diff or "")
        answer = next(
            (r for r in records[position + 1 :] if _changes(r, comment.files, flagged)), None
        )
        if flagged and answer is not None:
            found.append(_pain_point(comment, answer))
    return found


def _changes(record: Record, paths: tuple[str, ...], lines: frozenset[str]) -> bool:
    if record.kind != Kind.EDIT or record.exit_code == 1 or record.diff is None:
        return False
    return bool(set(record.files) & set(paths)) and bool(removed_lines(record.diff) & lines)


def _pain_point(comment: Record, answer: Record) -> PainPoint:
    return PainPoint(
        signature=Signature(Signal.REVIEW_FLAG, comment.files[:1]),
        session_id=comment.session_id,
        step=comment.step,
        record_refs=((comment.session_id, comment.step), (answer.session_id, answer.step)),
    )
