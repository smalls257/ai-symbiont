"""Signal: the developer correcting the agent.

Two ways to know a user turn is a correction:

- the dataset labelled it (`correction` or `rejection` in the record's tags,
  e.g. SWE-chat's pushback mark), or
- unlabelled: since the previous user turn a test run failed, and the turn
  names a file the agent edited in that stretch ("you broke dialect.py").

Key `(file, first 8 words)`: the file is one the turn names and the agent had
edited, else "-"; the words are lowercased with punctuation dropped, so the
note can quote how the developer put it.
"""

import re
from collections.abc import Sequence

from symbiont.miner.failing_tests import failing_test_files
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.records.schema import Kind, Record

CORRECTION_TAGS = frozenset({"correction", "rejection"})
KEY_WORDS = 8
NO_FILE = "-"
_WORD = re.compile(r"[\w'./-]*\w")


def find_corrections(session: Sequence[Record]) -> list[PainPoint]:
    """Find user turns that push back on what the agent just did."""
    found = []
    edited_ever: list[str] = []
    edited_since_turn: list[str] = []
    failed_since_turn = False
    for record in session:
        if record.kind == Kind.USER_TURN:
            if CORRECTION_TAGS & set(record.tags):
                found.append(_pain_point(record, _named_file(record.raw, edited_ever)))
            elif failed_since_turn and (named := _named_file(record.raw, edited_since_turn)):
                found.append(_pain_point(record, named))
            edited_since_turn, failed_since_turn = [], False
        elif record.kind == Kind.EDIT and record.exit_code != 1:
            edited_ever += record.files
            edited_since_turn += record.files
        elif failing_test_files(record):
            failed_since_turn = True
    return found


def _named_file(text: str, edited: list[str]) -> str | None:
    for path in reversed(edited):
        for name in (path, path.rsplit("/", 1)[-1]):
            if re.search(rf"(?<![\w.-]){re.escape(name)}(?!\w)", text):
                return path
    return None


def _pain_point(turn: Record, path: str | None) -> PainPoint:
    words = " ".join(_WORD.findall(turn.raw.lower())[:KEY_WORDS])
    return PainPoint(
        signature=Signature(Signal.CORRECTION, (path or NO_FILE, words)),
        session_id=turn.session_id,
        step=turn.step,
        record_refs=((turn.session_id, turn.step),),
    )
