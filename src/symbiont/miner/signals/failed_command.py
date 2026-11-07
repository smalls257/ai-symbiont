"""Signal: a command that exited non-zero, keyed by the attempt and how it broke.

Exit 1 from grep, diff, cmp, test and `[` is an answer ("no match"), not a failure; exit 2 and
above still is. When the text cannot tell which program set the status, exit 1 counts.
A planned failure (an assertion in a test edited this session) is not a mistake, and neither is
an interrupt: the user stopped the command, it did not break.
"""

from collections.abc import Sequence

from symbiont.miner.commands import inline_script_program, normalise_command, status_program
from symbiont.miner.failure_keys import is_interrupt, what_broke
from symbiont.miner.failure_program import failing_program
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.planned_failure import FailureKind, failure_kind
from symbiont.records.schema import Kind, Record
from symbiont.records.session_tags import REFUSED_TAG

EXIT_1_IS_AN_ANSWER = frozenset(
    {"grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack", "git grep", "diff", "cmp", "test", "["}
)


def find_failed_commands(session: Sequence[Record]) -> list[PainPoint]:
    """Find commands that exited non-zero, excluding exit 1 from answer-by-status tools.

    A planned failure (an assertion in a test written this session) is not a mistake: skipped.
    """
    return [
        _pain_point(record)
        for position, record in enumerate(session)
        if _failed(record) and failure_kind(record, session[:position]) is FailureKind.MISTAKE
    ]


def _failed(record: Record) -> bool:
    # exit_code None means the harness never reported one: unknown, so not counted.
    if record.kind != Kind.COMMAND or record.exit_code in (None, 0) or is_interrupt(record):
        return False
    if REFUSED_TAG in record.tags:  # the tool rejected the input; the command never ran
        return False
    return not (record.exit_code == 1 and _answered_no(record.command or ""))


def _answered_no(command: str) -> bool:
    return status_program(command) in EXIT_1_IS_AN_ANSWER


def _pain_point(record: Record) -> PainPoint:
    command = record.command or ""
    inline = inline_script_program(command)
    if inline:
        program, target = "python", "<inline>"
    else:
        target = normalise_command(command)[1]
        program = failing_program(command)
    key = (program, target, what_broke(record, program, inline=inline is not None))
    return PainPoint(
        signature=Signature(Signal.FAILED_COMMAND, key),
        session_id=record.session_id,
        step=record.step,
        record_refs=((record.session_id, record.step),),
    )
