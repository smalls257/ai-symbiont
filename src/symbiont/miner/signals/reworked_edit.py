"""Signal: an edit later reworked.

A later edit takes out text an earlier edit put in on the same file.

Pass one session, or the sessions of one task chain in the order they ran.
Never pass parallel attempts at the same task: they all start from the same
code, so each would look like it reworked the others.

Edits the editor rejected changed nothing and are skipped. Edits without a
diff (an undo) are skipped too: what they changed is unknown, and calling
them rework would be a guess.
"""

from collections import defaultdict
from collections.abc import Sequence

from symbiont.miner.diffs import added_lines, removed_lines
from symbiont.miner.painpoint import PainPoint, RecordRef, Signal, Signature
from symbiont.records.schema import Kind, Record


def find_reworked_edits(records: Sequence[Record]) -> list[PainPoint]:
    """Find edits that take out lines an earlier edit on the same file put in."""
    earlier: dict[str, list[tuple[Record, frozenset[str]]]] = defaultdict(list)
    found = []
    for record in records:
        if not _applied_with_content(record):
            continue
        for path in record.files:
            undone = [e for e, added in earlier[path] if added & removed_lines(record.diff or "")]
            if undone:
                found.append(_pain_point(path, undone, record))
            earlier[path].append((record, added_lines(record.diff or "")))
    return found


def _applied_with_content(record: Record) -> bool:
    return record.kind == Kind.EDIT and record.exit_code != 1 and record.diff is not None


def _pain_point(path: str, undone: list[Record], rework: Record) -> PainPoint:
    refs: tuple[RecordRef, ...] = tuple((r.session_id, r.step) for r in [*undone, rework])
    return PainPoint(
        signature=Signature(Signal.REWORKED_EDIT, (path,)),
        session_id=rework.session_id,
        step=rework.step,
        record_refs=refs,
    )
