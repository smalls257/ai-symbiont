"""Whether the agent's first step after a failure fixed it: then it knew the fix already.

A failure fixed that way teaches nothing, so it is neither a lesson nor worth a look. Callers ask
it only of fixes that left the code alone: a one-edit code fix may carry what the code needs.
Pure: records in, verdict out.
"""

from collections.abc import Sequence

from symbiont.miner.commands import command_stages, program_words
from symbiont.miner.complaint_line import complaint_of
from symbiont.miner.failure_signature import failure_detail
from symbiont.miner.read_only import is_read_only
from symbiont.miner.resolutions import later_success_of, subcommand_of
from symbiont.records.schema import Kind, Record

# What counts as the agent doing something between a failure and its pass.
_ACTIONS = frozenset({Kind.COMMAND, Kind.EDIT, Kind.READ})


def fixed_right_away(failed: Record, records: Sequence[Record]) -> bool:
    """The agent's first step fixed it: alone before the pass, the setup, or chained into the pass.

    A first step counts even when the retry then broke some other way, never when it did not take.
    """
    success = later_success_of(failed, records)
    if success is None:
        return False
    between = [r for r in records if failed.step < r.step < success.step and r.kind in _ACTIONS]
    if not between:
        return len(command_stages(success.command or "")) > 1
    if not _changed_something(between[0]):
        return False
    return len(between) == 1 or _retried_past_it(failed, between[1:])


def _retried_past_it(failed: Record, after: Sequence[Record]) -> bool:
    """The next try of the same command no longer printed the failure's error line."""
    wanted = _program_of(failed.command or "")
    retry = next(
        (r for r in after if r.kind is Kind.COMMAND and _program_of(r.command or "") == wanted),
        None,
    )
    error = _error_line(failed.raw)
    return retry is not None and bool(error) and _error_line(retry.raw) != error


def _error_line(output: str) -> str:
    return complaint_of(output) or failure_detail(output)


def _program_of(command: str) -> tuple[str, str]:
    return (program_words(command)[0], subcommand_of(command))


def _changed_something(action: Record) -> bool:
    """A step that worked and changed things: a look-around or a failed install fixed nothing."""
    if action.exit_code not in (0, None):
        return False
    return action.kind is Kind.EDIT or (
        action.kind is Kind.COMMAND and not is_read_only(action.command or "")
    )
