"""Hold-out ids: which spelling of a benchmark task id is which.

Pure (no I/O) so mining, which refuses held-out tasks before a lesson is
stored, the Route B dataset builder, which must never train on them, and the
training-manifest check share one rule. Import it from here.
"""

import re
from collections.abc import Iterable

from symbiont.records.schema import Record

_BENCHMARK_ID = re.compile(r"^([\w.-]+?)(?:__|/)([\w.-]+?)[-#](\d+)$")


class HoldOutViolationError(ValueError):
    """A held-out (scored) task's trajectory was offered to the store or a dataset."""

    def __init__(self, task_id: str, session_id: str):
        super().__init__(
            f"task {task_id!r} (session {session_id!r}) is held out for scoring "
            "and must not enter this store"
        )
        self.task_id = task_id


class UnrecognisedTaskIdError(ValueError):
    """A task id in no known benchmark spelling.

    It cannot be compared with the hold-out set; guessing would make the guard a no-op.
    """

    def __init__(self, task_id: str):
        super().__init__(
            f"task id {task_id!r} is not a benchmark id (owner__repo-123 or owner/repo#123); "
            "it cannot be checked against the hold-out set"
        )
        self.task_id = task_id


def normalise_task_id(task_id: str) -> str:
    """Map `tobymao__sqlglot-1234` and `tobymao/sqlglot#1234` to `tobymao/sqlglot#1234`.

    Raises UnrecognisedTaskIdError for anything else.
    """
    found = _BENCHMARK_ID.match(task_id.strip())
    if not found:
        raise UnrecognisedTaskIdError(task_id)
    owner, repo, number = found.groups()
    return f"{owner.lower()}/{repo.lower()}#{number}"


def refuse_held_out(records: Iterable[Record], held_out_tasks: frozenset[str]) -> None:
    """Raise HoldOutViolationError naming the first record of a held-out task.

    With nothing held out, task ids are free-form (the developer's own
    projects). Otherwise every id on both sides must be a benchmark id, and an
    id in neither spelling raises UnrecognisedTaskIdError.
    """
    held_out = {normalise_task_id(t) for t in held_out_tasks}
    if not held_out:
        return
    for record in records:
        if record.task_id is not None and normalise_task_id(record.task_id) in held_out:
            raise HoldOutViolationError(record.task_id, record.session_id)
