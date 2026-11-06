"""Which kind of known fix a resolution shows, if any.

A lesson that says "it passed when you ran it again" teaches nothing. Only two
resolutions carry something worth saying: an edit to the codebase, or the same program run
correctly after a wrong invocation. Everything else is struggle: counted, never taught.
"""

from collections.abc import Sequence
from enum import StrEnum

from symbiont.miner.changes import applied_edit
from symbiont.miner.codebase import repo_relative
from symbiont.miner.failure_keys import is_invocation_failure
from symbiont.miner.painpoint import PainPoint, Signal
from symbiont.records.schema import Record


class FixKind(StrEnum):
    """The two resolutions that teach something."""

    CODE_FIX = "code_fix"
    CORRECTED_COMMAND = "corrected_command"


def fix_kind(
    pain: PainPoint, steps: Sequence[Record], repo_names: frozenset[str] = frozenset()
) -> FixKind | None:
    """The kind of known fix `steps` (the resolution's own, never those made alongside) show."""
    if any(_edits_codebase(step, repo_names) for step in steps):
        return FixKind.CODE_FIX
    corrected = (
        steps
        and pain.signature.signal is Signal.FAILED_COMMAND
        and is_invocation_failure(pain.signature.key[-1])
    )
    return FixKind.CORRECTED_COMMAND if corrected else None


def _edits_codebase(step: Record, repo_names: frozenset[str]) -> bool:
    """An applied edit whose first file lies inside the codebase."""
    return (
        applied_edit(step)
        and bool(step.files)
        and repo_relative(step.files[0], repo_names) is not None
    )
