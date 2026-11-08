"""Signal: review feedback that was later acted on.

A review hunk holds when a later edit removes a line it added. A reviewer comment in `gh` output
(`review_comments_in`) holds when a later applied edit touched its file; nitpicks, the agent's own
posted text and each repeat of a comment id are not judged. Key `(path, reviewer, gist)`.
"""

from collections.abc import Sequence
from itertools import islice

from symbiont.miner.changes import applied_edit
from symbiont.miner.diffs import added_lines, removed_lines
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.review_comments import ReviewComment, review_comments_in
from symbiont.miner.review_gist import TEAMMATE, Severity, gist_of
from symbiont.records.schema import Kind, Record

OWN_TEXT_CHARS = 80
OWN_TEXT_MIN_CHARS = 40


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
    edited = {name for r in records if applied_edit(r) for name in r.files if name}
    earlier = _EarlierCommands()
    found = []
    for position, record in enumerate(records):
        for comment in review_comments_in(record):
            if comment.comment_id in seen:
                continue
            seen.add(comment.comment_id)
            answer = _answer(comment, records, position, edited)
            if answer is not None and not earlier.contain(comment.body):
                key = (comment.path, comment.reviewer, comment.gist)
                found.append(_pain_point(record, answer, key))
        earlier.add(record.command)
    return found


class _EarlierCommands:
    """The commands walked past so far, whitespace-normalized once, searchable as one text."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._joined: str | None = ""

    def add(self, command: str | None) -> None:
        if command:
            self._parts.append(_flat(command))
            self._joined = None

    def contain(self, body: str) -> bool:
        """The agent's own posted reply comes back in the next fetch; it is not feedback.

        A body under OWN_TEXT_MIN_CHARS is too short to tell a post from an echo or a grep.
        """
        opening = _flat(body)[:OWN_TEXT_CHARS]
        if len(opening) < OWN_TEXT_MIN_CHARS:
            return False
        if self._joined is None:
            self._joined = "\n".join(self._parts)
        return opening in self._joined


def _answer(
    comment: ReviewComment, records: Sequence[Record], position: int, edited: set[str]
) -> Record | None:
    if comment.severity is Severity.NITPICK or not comment.path:
        return None
    later = islice(records, position + 1, None)
    return next((r for r in later if _edits_path(r, comment.path, edited)), None)


def _edits_path(record: Record, path: str, edited: set[str]) -> bool:
    return applied_edit(record) and any(_same_file(name, path, edited) for name in record.files)


def _same_file(name: str, path: str, edited: set[str]) -> bool:
    """Equal paths, or one is the other's tail after a "/" (absolute vs repo-relative).

    A bare file name (no directory) is ambiguous, so it matches a longer path only when the
    session edited exactly one file of that name.
    """
    if not name or not path:
        return False
    if name == path:
        return True
    longer, shorter = (name, path) if len(name) > len(path) else (path, name)
    if not longer.endswith("/" + shorter):
        return False
    return "/" in shorter or sum(f.rsplit("/", 1)[-1] == shorter for f in edited) == 1


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
