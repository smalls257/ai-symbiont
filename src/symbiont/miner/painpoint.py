"""Pain points: places in history where something went wrong.

A signature is the *kind* of trouble in readable, normalised fields
(`("pytest", "tests/test_tokens.py", "ImportError")`), never a hash, so a
note can say in prose what went wrong and where. A pain point is one
occurrence, pointing back at the original records rather than copying them.
"""

from dataclasses import dataclass
from enum import StrEnum

RecordRef = tuple[str, int]  # (session_id, step)


class Signal(StrEnum):
    """The kinds of trouble the miner recognises, one per file under `signals/`."""

    FAILED_COMMAND = "failed_command"
    REWORKED_EDIT = "reworked_edit"
    REVIEW_FLAG = "review_flag"
    CORRECTION = "correction"
    LOOP = "loop"
    BLAST_RADIUS = "blast_radius"


@dataclass(frozen=True)
class Signature:
    """The kind of trouble, comparable across sessions so repeats can be counted."""

    signal: Signal
    key: tuple[str, ...]


@dataclass(frozen=True)
class PainPoint:
    """One occurrence of a signature, citing the records it came from."""

    signature: Signature
    session_id: str
    step: int
    record_refs: tuple[RecordRef, ...]
