"""Signal: the developer correcting the agent.

A user turn is a correction when the dataset labeled it, when it pastes a failing test run or red
CI check (`pasted_failure.py`), or when a test failed since the previous turn and it names a file
the agent edited. Key `(file, first 8 words)`; a pasted failure is keyed `(its file, "the CI run
failed at <check>")`, so the same red check in two sessions counts as a repeat.
"""

import re
from collections.abc import Sequence

from symbiont.miner.failing_tests import failing_test_files
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.pasted_failure import GENERIC_CHECK, PastedFailure, pasted_failure
from symbiont.records.ours import OUR_OUTPUT_RECORD_TAG
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
            elif (pasted := _pasted(record)) is not None:
                found.append(_ci_pain_point(record, pasted))
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


def _pasted(turn: Record) -> PastedFailure | None:
    """The failure a turn pastes; our own delivered notes are not the developer's words."""
    return None if OUR_OUTPUT_RECORD_TAG in turn.tags else pasted_failure(turn.raw)


def _ci_pain_point(turn: Record, pasted: PastedFailure) -> PainPoint:
    """A correction whose evidence is the check that was red when the developer wrote."""
    said = "the CI run failed"
    if pasted.check != GENERIC_CHECK:
        said += f" at {pasted.check}"
    return PainPoint(
        signature=Signature(Signal.CORRECTION, (pasted.file, said)),
        session_id=turn.session_id,
        step=turn.step,
        record_refs=((turn.session_id, turn.step),),
    )
