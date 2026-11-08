"""Whether a command is the agent waiting for something, which is patience, not a loop.

`sleep 60 && gh run view 1` repeated is polling CI. A wait is a `sleep` with only read-only
stages besides it, or a watch the tool blocks on itself (`gh run watch`, `gh pr checks --watch`).
So is reading a background task's output, and checking again after saying "still running".
Pure: text in, verdict out.
"""

import re
import shlex

from symbiont.miner.commands import Stage, command_stages
from symbiont.miner.read_only import is_read_only

# The agent announcing a wait: "Still running. Let me check periodically." "Wait, I see it" is not.
_SAYS_WAITING = re.compile(
    r"\bstill (?:running|in progress|going|working)\b|\bperiodically\b"
    r"|\b(?:let me|i'?ll|i will|keep|continu\w*(?: to)?) (?:wait|poll|monitor)\w*"
    r"|\bwait(?:ing)? (?:for|until|on)\b",
    re.IGNORECASE,
)
# A step that asks running work how it is doing: `tmux-status-check`, `rollout status`,
# `--heartbeat`. Like a watch, it is set aside and the rest must be read-only.
_ASKS_STATUS = re.compile(r"^-*(?:[\w]+[-_])*(?:status|heartbeat)(?:[-_]\w+)*$")
_STATUS_FLAGS = frozenset({"--heartbeat", "--status"})
# Where Claude Code writes a background task's output; reading it is checking on the task.
_TASK_OUTPUT = re.compile(r"/tasks/[\w-]+\.output\b")


def says_waiting(text: str) -> bool:
    """True when the agent says it is waiting on something that is still running."""
    return bool(_SAYS_WAITING.search(text))


def is_task_output(path: str) -> bool:
    """True for a background task's output file, which grows while the task runs."""
    return bool(_TASK_OUTPUT.search(path))


def is_waiting(command: str) -> bool:
    """True when the command pauses or checks on running work and nothing else changes things."""
    stages = command_stages(command)
    if not any(_pauses(stage) for stage in stages):
        return False
    rest = _without_pauses(stages)
    return not rest or is_read_only(rest)


def _pauses(stage: Stage) -> bool:
    """A sleep, a blocking watch, a status check, or a look at a background task's output."""
    return (
        stage.program == "sleep"
        or _blocks_until_done(stage)
        or _asks_status(stage)
        or any(is_task_output(arg) for arg in stage.args)
    )


def _asks_status(stage: Stage) -> bool:
    if any(arg in _STATUS_FLAGS for arg in stage.args):
        return True
    return any(_ASKS_STATUS.match(word) for word in (stage.program, *stage.args[:3]))


def _without_pauses(stages: list[Stage]) -> str:
    """The command minus its pauses, so the rest can be judged read-only."""
    kept = [stage for stage in stages if not _pauses(stage)]
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
