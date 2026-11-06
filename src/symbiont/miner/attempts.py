"""What a record says about an attempt: did the command fail, was it a test run.

Patterns and turns lost read the same two facts; one definition keeps them from disagreeing.
"""

from symbiont.miner.commands import program_words
from symbiont.miner.failure_keys import is_interrupt
from symbiont.records.schema import Kind, Record

TEST_RUNNERS = frozenset({"pytest", "py.test", "unittest"})


def failed(record: Record) -> bool:
    """A command that exited non-zero and was not a Ctrl-C; an unreported exit is unknown."""
    return (
        record.kind == Kind.COMMAND
        and record.exit_code not in (None, 0)
        and not is_interrupt(record)
    )


def is_test_run(record: Record) -> bool:
    """A command whose working program is a test runner."""
    return record.kind == Kind.COMMAND and program_words(record.command or "")[0] in TEST_RUNNERS
