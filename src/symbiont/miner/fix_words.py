"""What fixed a failure, in one short plain phrase: file names and one command, never code.

The reader of a fix, a dashboard card or the agent's note, wants "edited vault.service.ts, then
re-ran pnpm exec", not a path, a diff line and a whole command line. Every consumer reads
`Lesson.resolution`, which holds this phrase, so the wording is fixed here and nowhere else.
"""

import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import NamedTuple

from symbiont.miner.commands import final_program_words
from symbiont.miner.credential_patterns import scrub
from symbiont.miner.failure_program import SUBCOMMAND_PROGRAMS, failing_program
from symbiont.miner.read_only import is_read_only
from symbiont.miner.resolutions import subcommand_after
from symbiont.records.schema import Kind, Record

# One phrase, one glance: past this the reader skips it (owner: "word vomit").
PHRASE_CHARS = 110
# A whole resolution, several pooled fixes included: what every note, card and summary may say.
RESOLUTION_CHARS = 140
NAMES_SHOWN = 2
_CUT = "…"
_EDITED = "edited "
# Package managers whose first word is what the command does; a fix names `pip install`, not `pip`.
_SUBCOMMAND_PROGRAMS = SUBCOMMAND_PROGRAMS | {"pip", "pip3", "poetry", "apt", "apt-get", "bundle"}
_OLD_EDIT = re.compile(r"edited `([^`]+)`")
_OLD_RAN = re.compile(r"ran `([^`]+)`")


class Step(NamedTuple):
    """One resolving step reduced to what the phrase needs: the files it edited or its command."""

    files: tuple[str, ...] = ()
    command: str = ""


def fix_phrase(steps: Sequence[Record], failed_program: str = "") -> str:
    """The steps as "edited X, then re-ran pnpm exec"; "" when they show no real change.

    `failed_program` is the failing program (`pnpm exec`): running it again reads "re-ran".
    Read-only steps and an edit with no file are no fix: "" lets every consumer say so.
    """
    plain = [_step_of(step) for step in steps]
    return phrase_of_steps(plain, failed_program)


def phrase_from_old_steps(texts: Sequence[str], failed_program: str = "") -> str:
    """The phrase for steps stored as "edited `path` to add `code`" and "ran `cmd`"."""
    steps = []
    for text in texts:
        if found := _OLD_EDIT.match(text):
            steps.append(Step(files=tuple(found.group(1).split(", "))))
        elif found := _OLD_RAN.match(text):
            steps.append(Step(command=found.group(1)))
    return phrase_of_steps(steps, failed_program)


def phrase_of_steps(steps: Sequence[Step], failed_program: str = "") -> str:
    """The plain phrase for reduced steps; "" when none is a real change."""
    names = edited_names(steps)
    command = last_command(steps, failed_program)
    parts = _in_order(steps, names, command, failed_program)
    return _capped(", then ".join(parts), PHRASE_CHARS)


def resolution_phrase(phrases: Sequence[str]) -> str:
    """One bounded phrase for a resolution; pooled twins read "X, and 3 other fixes"."""
    unique = tuple(dict.fromkeys(phrase for phrase in phrases if phrase))
    if len(unique) <= 1:
        return _capped(unique[0], RESOLUTION_CHARS) if unique else ""
    others = len(unique) - 1
    tail = f", and {others} other {'fix' if others == 1 else 'fixes'}"
    return _capped(unique[0], RESOLUTION_CHARS - len(tail)) + tail


def edited_names(steps: Sequence[Step]) -> tuple[str, ...]:
    """The scrubbed base names of the files the steps edited, in order, without repeats."""
    names = (scrub(_base(path)) for step in steps for path in step.files)
    return tuple(dict.fromkeys(name for name in names if name))


def edit_phrase(names: Sequence[str]) -> str:
    """`a.ts`, `a.ts and b.ts` or `5 files (a.ts, b.ts and 3 more)`; "" for no names."""
    if len(names) <= NAMES_SHOWN:
        return " and ".join(names)
    shown = ", ".join(names[:NAMES_SHOWN])
    return f"{len(names)} files ({shown} and {len(names) - NAMES_SHOWN} more)"


def edit_clause(phrase: str) -> str:
    """The "X" of a phrase that starts "edited X, then ..."; "" when it names no edit."""
    if not phrase.startswith(_EDITED):
        return ""
    return phrase.removeprefix(_EDITED).split(", then ")[0]


def command_name(command: str) -> str:
    """The program and subcommand of a command line: `npm install`, never its arguments."""
    program, args = final_program_words(command)
    if program not in _SUBCOMMAND_PROGRAMS:
        return program
    subcommand = subcommand_after(program, args)
    return program if subcommand == "-" else f"{program} {subcommand}"


def last_command(steps: Sequence[Step], failed_program: str = "") -> str:
    """The command worth naming: the last one that is not read-only or plumbing.

    With no edit in the steps, a command other than the failed program's own re-run wins: the
    install is the fix, the re-run only shows it worked. "" when there is none.
    """
    working = _working_commands(steps)
    other = [c for c in working if failing_program(c) != failed_program]
    edited = any(step.files for step in steps)
    return next(iter(working if edited or not other else other), "")


def _step_of(record: Record) -> Step:
    if record.kind == Kind.EDIT:
        return Step(files=tuple(record.files))
    return Step(command=record.command or "") if record.kind == Kind.COMMAND else Step()


def _working_commands(steps: Sequence[Step]) -> list[str]:
    """The steps' commands that change something, newest first."""
    commands = [step.command for step in steps if step.command]
    return [c for c in reversed(commands) if c.strip() and not is_read_only(c)]


def _in_order(
    steps: Sequence[Step], names: tuple[str, ...], command: str, failed_program: str
) -> list[str]:
    """The edit part and the command part, in the order they happened."""
    edit_at = max((i for i, s in enumerate(steps) if s.files), default=-1)
    ran_at = max((i for i, s in enumerate(steps) if command and s.command == command), default=-1)
    parts = []
    if names:
        parts.append((edit_at, _EDITED + edit_phrase(names)))
    if command:
        parts.append((ran_at, _ran(command, failed_program)))
    return [text for _, text in sorted(parts)]


def _ran(command: str, failed_program: str) -> str:
    program = command_name(command)
    again = bool(failed_program) and failing_program(command) == failed_program
    return f"re-ran {program}" if again else f"ran {program}"


def _base(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).name


def _capped(phrase: str, limit: int) -> str:
    """The phrase cut at a word boundary to `limit`, never leaving an open bracket."""
    if len(phrase) <= limit:
        return phrase
    cut = phrase[: limit - len(_CUT)].rsplit(" ", 1)[0]
    if cut.count("(") > cut.count(")"):
        cut = cut[: cut.rindex("(")]
    return cut.rstrip(" ,(") + _CUT
