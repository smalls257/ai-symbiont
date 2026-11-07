"""Signal: the developer correcting the agent.

A user turn is a correction when the dataset tagged it (`correction`, `rejection`) or a test run
failed since the last turn and the turn names a file the agent edited. "ok" and "/compact" never
are. Key `(file, first 8 words)`: the file is one the turn names, else "-"; the words are
lowercased with punctuation dropped, so the note can quote how the developer put it.
"""

import re
from collections.abc import Sequence

from symbiont.miner.empty_correction import is_bare_acknowledgment
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
            pain = _turn_correction(
                record, edited_ever, edited_since_turn if failed_since_turn else []
            )
            if pain is not None:
                found.append(pain)
            edited_since_turn, failed_since_turn = [], False
        elif record.kind == Kind.EDIT and record.exit_code != 1:
            edited_ever += record.files
            edited_since_turn += record.files
        elif failing_test_files(record):
            failed_since_turn = True
    return found


def _turn_correction(
    turn: Record, edited_ever: list[str], edited_after_failure: list[str]
) -> PainPoint | None:
    """The correction a user turn is, or None; "ok" and "/compact" teach nothing."""
    if is_bare_acknowledgment(turn.raw):
        return None
    if CORRECTION_TAGS & set(turn.tags):
        return _pain_point(turn, _named_file(turn.raw, edited_ever))
    named = _named_file(turn.raw, edited_after_failure)
    return _pain_point(turn, named) if named else None


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
