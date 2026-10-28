"""Recall: which past records answer a plain question."""

import re
from collections.abc import Iterable

from symbiont.records.schema import Record

DEFAULT_LIMIT = 2
_WORD = re.compile(r"[a-z0-9_]{3,}")


def relevant_records(
    question: str, records: Iterable[Record], *, limit: int = DEFAULT_LIMIT
) -> list[Record]:
    """Records whose command or files share words with the question, best first."""
    wanted = set(_WORD.findall(question.lower()))
    scored = [(len(wanted & _words(record)), record) for record in records]
    hits = [(score, r) for score, r in scored if score > 0]
    hits.sort(key=lambda hit: (-hit[0], hit[1].session_id, hit[1].step))
    return [record for _, record in hits[:limit]]


def _words(record: Record) -> set[str]:
    if not (record.command or record.files):
        return set()
    text = " ".join([record.command or "", *record.files])
    return set(_WORD.findall(text.lower()))
