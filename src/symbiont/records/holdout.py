"""Hold-out ids: which spelling of a benchmark task id is which.

Pure (no I/O) so the store, which refuses held-out tasks, and the Route B
dataset builder, which must never train on them, share one rule. Import it from
here; `symbiont.store.local` does not re-export it.
"""

import re

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
