"""PLUG-AGENT-2: what counts as a known mistake and a repeat of one, frozen before the smoke test.

A failure's key is (error class, program, target file). A generic key such as
(ModuleNotFoundError, python) says only "a Python command failed", so a part that is empty or "-"
(no file-like argument) gives no key and never counts as known (counting it would make
every Python task "repeat" it). Pure.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from plug_agent_notes import Failure, failure_of

NO_TARGET = "-"
RETURNCODE = re.compile(r"<returncode>(-?\d+)</returncode>")

Key = tuple[str, str, str]


def key_of(failure: Failure) -> Key | None:
    """(error class, program, file) or None when any part is empty or has no file-like target."""
    error_class, program = failure.key()
    target = failure.file
    if not error_class or program in ("", NO_TARGET) or target in ("", NO_TARGET):
        return None
    return (error_class, program, target)


def failures_in(messages: Sequence[Mapping]) -> list[Failure | None]:
    """One entry per executed command of a mini-SWE-agent tool-calling history: its Failure, or
    None when it passed or names no error class."""
    found: list[Failure | None] = []
    command = None
    for message in messages:
        if message["role"] == "assistant":
            calls = message.get("tool_calls") or []
            command = (
                json.loads(calls[0]["function"]["arguments"]).get("command") if calls else None
            )
        elif message["role"] == "tool" and command:
            code = RETURNCODE.search(message["content"])
            found.append(
                failure_of(command, int(code.group(1)) if code else None, message["content"])
            )
            command = None
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
