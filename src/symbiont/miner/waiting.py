"""Whether a command is the agent waiting for something, which is patience, not a loop.

`sleep 60 && gh run view 1` repeated is polling CI. A wait is a `sleep` with only read-only
stages besides it, or a watch the tool blocks on itself (`gh run watch`, `gh pr checks --watch`).
Pure: command text in, verdict out.
"""

import shlex

from symbiont.miner.commands import Stage, command_stages
from symbiont.miner.read_only import is_read_only


def is_waiting(command: str) -> bool:
    """True for sleep-and-look polling or a `gh` watch, when nothing else in it changes things."""
    stages = command_stages(command)
    if not any(_pauses(stage) for stage in stages):
        return False
    rest = _without_pauses_that_block(stages)
    return not rest or is_read_only(rest)


def _pauses(stage: Stage) -> bool:
    return stage.program == "sleep" or _blocks_until_done(stage)


def _without_pauses_that_block(stages: list[Stage]) -> str:
    """The command minus its blocking watches, so the rest can be judged read-only."""
    kept = [stage for stage in stages if not _blocks_until_done(stage)]
    return "".join(
        (" | " if stage.piped and index else " ; " if index else "")
        + shlex.join((stage.program, *stage.args))
        for index, stage in enumerate(kept)
    )


def _blocks_until_done(stage: Stage) -> bool:
    if stage.program != "gh":
        return False
    return stage.args[:2] == ("run", "watch") or (
        stage.args[:2] == ("pr", "checks") and "--watch" in stage.args
    )
