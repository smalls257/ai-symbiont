"""Whether the agent fixed the setup, not the code, between a failure and the later pass.

Decided from the session's own commands, not from a list of known installers: `docker compose up`
is no install verb, yet it is what made the command pass. A look-around and a re-run of the failed
command itself are not setup.
"""

from collections.abc import Sequence

from symbiont.miner.commands import normalise_command, program_words
from symbiont.miner.resolutions import later_success_of, subcommand_of
from symbiont.miner.screen import PROBES
from symbiont.miner.secrets import scrub
from symbiont.records.schema import Kind, Record

COMMAND_CHARS = 80


def setup_command(failed: Record, records: Sequence[Record]) -> str | None:
    """The first command run between `failed` and its later pass that is neither it nor a probe.

    None when the command never passed later or nothing else ran. The text is scrubbed.
    """
    success = later_success_of(failed, records)
    if success is None:
        return None
    between = sorted(
        (r for r in records if failed.step < r.step < success.step and r.kind is Kind.COMMAND),
        key=lambda record: record.step,
    )
    own = _identity(failed.command or "")
    for record in between:
        command = record.command or ""
        if program_words(command)[0] in PROBES or _identity(command) == own:
            continue
        return _short(scrub(command))
    return None


def _short(command: str) -> str:
    first = (command.strip().splitlines() or [""])[0]
    return first if len(first) <= COMMAND_CHARS else first[: COMMAND_CHARS - 3] + "..."


def _identity(command: str) -> tuple[tuple[str, str], str]:
    """Program, target and subcommand: `npm install` is not `npm test`."""
    return (normalise_command(command), subcommand_of(command))
