"""What fixed a failure, in one short plain phrase: file names and one command, never code.

The reader of a fix, a dashboard card or the agent's note, wants "edited vault.service.ts, then
re-ran pnpm exec", not a path, a diff line and a whole command line. Every consumer reads
`Lesson.resolution`, which holds this phrase, so the wording is fixed here and nowhere else.
"""

from collections.abc import Sequence
from pathlib import PurePosixPath

from symbiont.miner.commands import final_program_words
from symbiont.miner.failure_program import SUBCOMMAND_PROGRAMS, failing_program
from symbiont.miner.read_only import is_read_only
from symbiont.miner.resolutions import subcommand_after
from symbiont.records.schema import Kind, Record

# One phrase, one glance: past this the reader skips it (owner: "word vomit").
PHRASE_CHARS = 110
NAMES_SHOWN = 2
_CUT = "…"
_EDITED = "edited "
# Package managers whose first word is what the command does; a fix names `pip install`, not `pip`.
_SUBCOMMAND_PROGRAMS = SUBCOMMAND_PROGRAMS | {"pip", "pip3", "poetry", "apt", "apt-get", "bundle"}
_NO_COMMAND_LEFT = "ran another command"


def fix_phrase(steps: Sequence[Record], failed_program: str = "") -> str:
    """The steps as "edited X, then re-ran pnpm exec"; "" when there are no steps.

    `failed_program` is the failing program (`pnpm exec`): running it again reads "re-ran".
    """
    if not steps:
        return ""
    names = edited_names(steps)
    command = last_command(steps, failed_program)
    parts = _in_order(steps, names, command, failed_program)
    phrase = ", then ".join(parts) if parts else _NO_COMMAND_LEFT
    return _capped(phrase)


def edited_names(steps: Sequence[Record]) -> tuple[str, ...]:
    """The base names of the files the edit steps touched, in order, without repeats."""
    names = (_base(path) for step in steps if step.kind == Kind.EDIT for path in step.files)
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


def last_command(steps: Sequence[Record], failed_program: str = "") -> str:
    """The command worth naming: the last one that is not read-only or plumbing.

    With no edit in the steps, a command other than the failed program's own re-run wins: the
    install is the fix, the re-run only shows it worked. "" when there is none.
    """
    working = _working_commands(steps)
    other = [c for c in working if failing_program(c) != failed_program]
    edited = any(step.kind == Kind.EDIT for step in steps)
    return next(iter(working if edited or not other else other), "")


def _working_commands(steps: Sequence[Record]) -> list[str]:
    """The steps' commands that change something, newest first."""
    commands = [s.command or "" for s in steps if s.kind == Kind.COMMAND]
    return [c for c in reversed(commands) if c.strip() and not is_read_only(c)]


def _in_order(
    steps: Sequence[Record], names: tuple[str, ...], command: str, failed_program: str
) -> list[str]:
    """The edit part and the command part, in the order they happened."""
    edit_at = max((i for i, s in enumerate(steps) if s.kind == Kind.EDIT), default=-1)
    ran_at = max((i for i, s in enumerate(steps) if s.command == command and command), default=-1)
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


def _capped(phrase: str) -> str:
    if len(phrase) <= PHRASE_CHARS:
        return phrase
    return phrase[: PHRASE_CHARS - len(_CUT)].rstrip(" ,(") + _CUT
