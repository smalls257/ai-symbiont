"""Which kind of known fix a resolution shows, if any.

A lesson that says "it passed when you ran it again" teaches nothing. Only two
resolutions carry something worth saying: an edit to the codebase, or the same program run
correctly after a wrong invocation. Everything else is struggle: counted, never taught.
"""

from collections.abc import Sequence
from enum import StrEnum

from symbiont.miner.changes import applied_edit
from symbiont.miner.failure_keys import is_invocation_failure
from symbiont.miner.painpoint import PainPoint, Signal
from symbiont.records.schema import Record

_THROWAWAY_DIRS = ("/tmp/", "/var/folders/", "/private/tmp/")
# Top-level files that are the project itself, not a scratch script dropped in the root.
_PROJECT_FILES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "conftest.py",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Makefile",
    }
)


class FixKind(StrEnum):
    """The two resolutions that teach something."""

    CODE_FIX = "code_fix"
    CORRECTED_COMMAND = "corrected_command"


def fix_kind(pain: PainPoint, steps: Sequence[Record]) -> FixKind | None:
    """The kind of known fix `steps` (the resolution's own, never those made alongside) show."""
    if any(applied_edit(step) and in_codebase(step.files) for step in steps):
        return FixKind.CODE_FIX
    corrected = (
        steps
        and pain.signature.signal is Signal.FAILED_COMMAND
        and is_invocation_failure(pain.signature.key[-1])
    )
    return FixKind.CORRECTED_COMMAND if corrected else None


def in_codebase(files: Sequence[str]) -> bool:
    """True when the first edited file is part of the project, not a scratch file.

    The miner does not know the repository root, so a scratch file is recognized by where it
    sits: a temporary directory, a hidden tool directory, or a loose script in the top level.
    """
    if not files:
        return False
    path = files[0].removeprefix("./")
    if path.startswith(_THROWAWAY_DIRS) or any(p.startswith(".") for p in path.split("/")[:-1]):
        return False
    return path.startswith("/") or "/" in path or path in _PROJECT_FILES
