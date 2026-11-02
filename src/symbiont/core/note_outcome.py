"""What the agent did after a shown note: followed, ignored or burned.

The log answers "did the note help" without a UI: for each of the next ACTIONS_WATCHED actions the
agent took, was it the lesson's fix, something unrelated, or something that failed.
"""

import re
from enum import StrEnum

ACTIONS_WATCHED = 3
_CHAIN = re.compile(r"&&|\|\||[;|\n]")


class Outcome(StrEnum):
    """One action after a note."""

    FOLLOWED = "followed"  # ran one of the lesson's fix commands
    IGNORED = "ignored"  # unrelated, and it did not fail
    BURNED = "burned"  # not the fix, and it ended in a new error


def classify_action(fixes: tuple[str, ...], command: str | None, exit_code: int | None) -> Outcome:
    """The fix wins even if it failed (the agent did what the note said); else a failure burns."""
    if command and _runs_fix(fixes, command):
        return Outcome.FOLLOWED
    if exit_code:
        return Outcome.BURNED
    return Outcome.IGNORED


def _runs_fix(fixes: tuple[str, ...], command: str) -> bool:
    """Whether any `&&`/`;`/pipe segment of the command is a fix, or starts with one."""
    segments = [part.strip() for part in _CHAIN.split(command)]
    return any(part == fix or part.startswith(fix + " ") for part in segments for fix in fixes)
