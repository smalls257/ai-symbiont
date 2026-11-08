"""Whether a command is the agent waiting for something, which is patience, not a loop.

`sleep 60 && gh run view 1` repeated is polling CI. A wait is a `sleep` with only read-only
stages besides it, or a watch the tool blocks on itself (`gh run watch`, `gh pr checks --watch`).
Pure: command text in, verdict out.
"""

from symbiont.miner.commands import Stage, command_stages
from symbiont.miner.read_only import is_read_only


def is_waiting(command: str) -> bool:
    """True for a sleep-and-look polling command or a blocking `gh` watch."""
    stages = command_stages(command)
    if any(_blocks_until_done(stage) for stage in stages):
        return True
    return any(stage.program == "sleep" for stage in stages) and is_read_only(command)


def _blocks_until_done(stage: Stage) -> bool:
    if stage.program != "gh":
        return False
    return stage.args[:2] == ("run", "watch") or (
        stage.args[:2] == ("pr", "checks") and "--watch" in stage.args
    )
