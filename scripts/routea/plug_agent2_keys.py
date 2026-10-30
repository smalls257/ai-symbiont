"""PLUG-AGENT-2: what counts as a known mistake and a repeat of one, frozen before the smoke test.

A failure's key is its normalized error line (plug_agent2_errorline.py). A failure whose line is
empty after masking has no key and never counts as known. Pure.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from plug_agent2_errorline import normalize_error_line
from plug_agent_notes import Failure, failure_of

RETURNCODE = re.compile(r"<returncode>(-?\d+)</returncode>")

Key = tuple[str, ...]


def key_of(failure: Failure) -> Key | None:
    """The normalized error line as a one-part key, or None when nothing meaningful is left."""
    line = normalize_error_line(failure.error)
    return (line,) if line else None


@dataclass(frozen=True)
class Executed:
    """One executed action of a tool-calling history and where it sits."""

    observation_index: int
    command: str
    output: str
    action_index: int  # position among the assistant message's actions
    action_count: int
    model_calls: int  # assistant messages up to and including this action's


def _commands_of(message: Mapping) -> list[str]:
    """The bash commands an assistant message asks for, in order."""
    actions = (message.get("extra") or {}).get("actions")
    if actions:
        return [str(action.get("command", "")) for action in actions]
    calls = message.get("tool_calls") or []
    return [json.loads(call["function"]["arguments"]).get("command", "") for call in calls]


def executed_actions(messages: Sequence[Mapping]) -> list[Executed]:
    """Every action paired with its observation message (the i-th action, the i-th tool reply)."""
    found: list[Executed] = []
    pending: list[tuple[int, str, int]] = []
    count, model_calls = 0, 0
    for index, message in enumerate(messages):
        if message["role"] == "assistant":
            model_calls += 1
            commands = _commands_of(message)
            count = len(commands)
            pending = [(i, command, count) for i, command in enumerate(commands)]
        elif message["role"] == "tool" and pending:
            position, command, total = pending.pop(0)
            found.append(Executed(index, command, message["content"], position, total, model_calls))
    return found


def failures_in(messages: Sequence[Mapping]) -> list[Failure | None]:
    """One entry per executed command: its Failure, or None when it passed or names no error
    class."""
    found: list[Failure | None] = []
    for step in executed_actions(messages):
        code = RETURNCODE.search(step.output)
        found.append(failure_of(step.command, int(code.group(1)) if code else None, step.output))
    return found


@dataclass(frozen=True)
class RunReading:
    """What one run shows about known mistakes (counts and keys only)."""

    failures: int
    keyless: int
    first_known: int | None  # index into the keyed failures, None when no known mistake happened
    repeated: bool  # the first known mistake's key failed again after that point
    any_key_repeats: int  # secondary: repeats of any keyed failure


def read_run(failures: Iterable[Failure | None], known: frozenset[Key]) -> RunReading:
    """The run's reading: the primary indicator and the secondary any-key repeat count."""
    keys: list[Key] = []
    failed = [f for f in failures if f is not None]
    for failure in failed:
        key = key_of(failure)
        if key is not None:
            keys.append(key)
    first = next((i for i, key in enumerate(keys) if key in known), None)
    repeated = first is not None and keys[first] in keys[first + 1 :]
    repeats = sum(key in keys[:i] for i, key in enumerate(keys))
    return RunReading(len(failed), len(failed) - len(keys), first, repeated, repeats)
