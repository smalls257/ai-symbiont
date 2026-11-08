"""Signal: review feedback that was later acted on.

A review hunk holds when a later edit removes a line it added. A reviewer comment in `gh` output
(`review_comments_in`) holds when a later applied edit touched its file; nitpicks, the agent's own
posted text and each repeat of a comment id are not judged. Key `(path, reviewer, gist)`.
"""

from collections.abc import Sequence

from symbiont.miner.changes import applied_edit
from symbiont.miner.diffs import added_lines, removed_lines
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.review_comments import ReviewComment, review_comments_in
from symbiont.miner.review_gist import TEAMMATE, Severity, gist_of
from symbiont.records.schema import Kind, Record

OWN_TEXT_CHARS = 80


def find_review_flags(records: Sequence[Record]) -> list[PainPoint]:
    """Find review feedback that a later edit answered."""
    return [*_hunk_flags(records), *_fetched_flags(records)]


def _hunk_flags(records: Sequence[Record]) -> list[PainPoint]:
    found = []
    for position, comment in enumerate(records):
        if comment.kind != Kind.REVIEW_COMMENT:
            continue
        flagged = added_lines(comment.diff or "")
        answer = next(
            (r for r in records[position + 1 :] if _changes(r, comment.files, flagged)), None
        )
        if flagged and answer is not None:
            key = (comment.files[0] if comment.files else "", TEAMMATE, gist_of(comment.raw))
            found.append(_pain_point(comment, answer, key))
    return found


def _fetched_flags(records: Sequence[Record]) -> list[PainPoint]:
    """One pain point per fetched comment id that is not a nitpick, not ours, and was acted on."""
    seen: set[str] = set()
    found = []
    for position, record in enumerate(records):
        for comment in review_comments_in(record):
            if comment.comment_id in seen:
                continue
            seen.add(comment.comment_id)
            answer = _answer(comment, records[position + 1 :])
            if answer is not None and not _is_own_text(comment, records[:position]):
                key = (comment.path, comment.reviewer, comment.gist)
                found.append(_pain_point(record, answer, key))
    return found


def _answer(comment: ReviewComment, later: Sequence[Record]) -> Record | None:
    if comment.severity is Severity.NITPICK or not comment.path:
        return None
    return next((r for r in later if _edits_path(r, comment.path)), None)


def _edits_path(record: Record, path: str) -> bool:
    """An applied edit of a file; paths match when one ends with the other (absolute or not)."""
    return applied_edit(record) and any(
        name.endswith(path) or path.endswith(name) for name in record.files if name
    )


def _is_own_text(comment: ReviewComment, earlier: Sequence[Record]) -> bool:
    """The agent's own posted reply comes back in the next fetch; it is not feedback."""
    opening = _flat(comment.body)[:OWN_TEXT_CHARS]
    return bool(opening) and any(opening in _flat(r.command or "") for r in earlier)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _changes(record: Record, paths: tuple[str, ...], lines: frozenset[str]) -> bool:
    if record.kind != Kind.EDIT or record.exit_code == 1 or record.diff is None:
        return False
    return bool(set(record.files) & set(paths)) and bool(removed_lines(record.diff) & lines)


def _pain_point(comment: Record, answer: Record, key: tuple[str, ...]) -> PainPoint:
    return PainPoint(
        signature=Signature(Signal.REVIEW_FLAG, key),
        session_id=comment.session_id,
        step=comment.step,
        record_refs=((comment.session_id, comment.step), (answer.session_id, answer.step)),
    )
