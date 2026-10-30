"""Signal: a command that exited non-zero.

The key names the attempt and how it broke, e.g.
`("pytest", "tests/dialects/test_duckdb.py", "ImportError")`, so the note can
say "this failed last time with an ImportError" in plain words.

Exit 1 is an answer, not a failure, for programs that use it to say "no":
grep and its kin ("no match"), diff and cmp ("files differ"), test and `[`
("false"). An empty search is the agent learning something, not a mistake.
Exit 2 and above from them is still a failure (bad pattern, missing file).
When the text cannot tell which program set the status (`pytest && grep`),
exit 1 counts as a failure: the signal is kept rather than guessed away.
"""

import re
from collections.abc import Sequence

from symbiont.miner.commands import normalise_command, status_program
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.records.schema import Kind, Record

_ERROR_CLASS = re.compile(r"\b([A-Z]\w*Error)\b")
EXIT_1_IS_AN_ANSWER = frozenset(
    {"grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack", "git grep", "diff", "cmp", "test", "["}
)


def find_failed_commands(session: Sequence[Record]) -> list[PainPoint]:
    """Find commands that exited non-zero, excluding exit 1 from answer-by-status tools."""
    return [_pain_point(record) for record in session if _failed(record)]


def _failed(record: Record) -> bool:
    # exit_code None means the harness never reported one: unknown, so not counted.
    if record.kind != Kind.COMMAND or record.exit_code in (None, 0):
        return False
    return not (record.exit_code == 1 and _answered_no(record.command or ""))


def _answered_no(command: str) -> bool:
    return status_program(command) in EXIT_1_IS_AN_ANSWER


def _pain_point(record: Record) -> PainPoint:
    key = (*normalise_command(record.command or ""), _what_broke(record))
    return PainPoint(
        signature=Signature(Signal.FAILED_COMMAND, key),
        session_id=record.session_id,
        step=record.step,
        record_refs=((record.session_id, record.step),),
    )


def _what_broke(record: Record) -> str:
    """Name the last error class in the output (where the run ended), else the exit code."""
    errors = _ERROR_CLASS.findall(record.raw)
    return errors[-1] if errors else f"exit {record.exit_code}"
