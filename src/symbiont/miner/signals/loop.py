"""Signal: the agent going round in circles.

A loop is the same action repeated close together with nothing learned and
nothing changed:

- the same command (whole text; only temp paths and spacing are evened out,
  so `python -c` one-liners, heredocs, sed ranges and grep patterns stay
  distinct), each time with the same exit code and the same output, or
- the same view of the same lines of a file (paging through a file is
  reading, not looping), each time successful.

Repeats must be within `window` steps of the previous one. An applied edit
ends every command streak (any change can alter a command's result) and the
read streaks of the files it changed. One pain point per streak, at the step
where it reaches `min_repeats`, citing every repeat.

The command key is the command as the agent typed it (shortened if long), not
the lossy `normalise_command` used to group failures across sessions.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from symbiont.miner.painpoint import PainPoint, RecordRef, Signal, Signature
from symbiont.records.schema import Kind, Record

MAX_KEY_CHARS = 120
_TEMP_PATH = re.compile(r"(?:/private)?(?:/tmp|/var/folders)/[^\s'\"]*")
_DURATION = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds)\b")
_ADDRESS = re.compile(r"\b0x[0-9a-fA-F]+\b")


_Result = tuple[int | None, str]


@dataclass
class _Streak:
    result: _Result
    repeats: list[Record] = field(default_factory=list)


def find_loops(
    session: Sequence[Record], min_repeats: int = 3, window: int = 10
) -> list[PainPoint]:
    """Find an action repeated `min_repeats` times with the same result inside `window` steps."""
    streaks: dict[tuple[str, ...], _Streak] = {}
    found = []
    for record in session:
        if _changed_files(record):
            _end_streaks_touched_by(streaks, record)
            continue
        key = _repeat_key(record)
        if key is None:
            continue
        streak = streaks.get(key)
        result = _result(record)
        if (
            streak is None
            or streak.result != result
            or record.step - streak.repeats[-1].step > window
        ):
            streak = streaks[key] = _Streak(result)
        streak.repeats.append(record)
        if len(streak.repeats) == min_repeats:
            found.append(_pain_point(key, streak.repeats))
    return found


def _changed_files(record: Record) -> bool:
    # A rejected edit (exit_code 1) changed nothing, so it does not end a loop.
    return record.kind == Kind.EDIT and record.exit_code != 1


def _end_streaks_touched_by(streaks: dict[tuple[str, ...], _Streak], edit: Record) -> None:
    for key in list(streaks):
        if key[0] == "command" or (key[0] == "read" and key[1] in edit.files):
            del streaks[key]


def _repeat_key(record: Record) -> tuple[str, ...] | None:
    if record.kind == Kind.COMMAND and record.command and record.command.strip():
        return ("command", _even_out(record.command))
    if record.kind == Kind.READ and len(record.files) == 1 and record.exit_code != 1:
        return ("read", record.files[0], _lines_shown(record.line_range))
    return None


def _result(record: Record) -> _Result:
    output = _ADDRESS.sub("<addr>", _DURATION.sub("<time>", _even_out(record.raw)))
    return (record.exit_code, output)


def _even_out(text: str) -> str:
    return " ".join(_TEMP_PATH.sub("<tmp>", text).split())


def _shown(command: str) -> str:
    if len(command) <= MAX_KEY_CHARS:
        return command
    return command[: MAX_KEY_CHARS - 3] + "..."


def _lines_shown(line_range: tuple[int, int] | None) -> str:
    if line_range is None:
        return "whole file"
    first, last = line_range
    return f"{first}-end" if last == -1 else f"{first}-{last}"


def _pain_point(key: tuple[str, ...], repeats: list[Record]) -> PainPoint:
    refs: tuple[RecordRef, ...] = tuple((r.session_id, r.step) for r in repeats)
    last = repeats[-1]
    if key[0] == "command":
        key = ("command", _shown(key[1]))
    return PainPoint(
        signature=Signature(Signal.LOOP, key),
        session_id=last.session_id,
        step=last.step,
        record_refs=refs,
    )
