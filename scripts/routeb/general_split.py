"""The held-out evaluation split for the general-lessons pilot, declared before any lesson exists.

No run, gold patch or upstream fix of an evaluation task may feed a lesson; every builder reads the
ids from the committed split file through `evaluation_ids`, so there is one list, not two. Pure
apart from reading that one file.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from general_kinds import TaskKind


class Pick(StrEnum):
    """Why a task is in the evaluation split."""

    IN_BAND = "plain solved 1 of 3 at cap 50"
    NEAR_BAND = "plain solved 2 of 3 at cap 50"
    EDITED_UNSOLVED = "plain never solved, edited a source file"
    SOLVED_AT_75 = "plain unsolved at cap 50, solved 1 of 2 at cap 75"
    UNSOLVED_NO_EDIT = "plain never solved, no source edit"


@dataclass(frozen=True)
class EvalTask:
    """One evaluation task: its declared kind and why it was picked."""

    task: str
    kind: TaskKind
    pick: Pick


def _task(number: int, kind: TaskKind, pick: Pick) -> EvalTask:
    return EvalTask(f"tobymao__sqlglot-{number}", kind, pick)


_BUG, _FEATURE = TaskKind.BUG, TaskKind.FEATURE
# Bugs: the strict 20-60% band at cap 50 (1 of 3), one M-size task near it, and never-solved small
# tasks whose plain run already edited code. 1379, 1944 and 3533 (2 of 3) stay lesson sources.
# Features: small-to-medium and run at least once by plain Glimmer; only 3111 was ever solved.
SPLIT = (
    _task(1309, _BUG, Pick.IN_BAND),
    _task(2095, _BUG, Pick.IN_BAND),
    _task(2443, _BUG, Pick.IN_BAND),
    _task(2529, _BUG, Pick.IN_BAND),
    _task(2658, _BUG, Pick.IN_BAND),
    _task(772, _BUG, Pick.IN_BAND),
    _task(4208, _BUG, Pick.NEAR_BAND),
    _task(2337, _BUG, Pick.EDITED_UNSOLVED),
    _task(3166, _BUG, Pick.EDITED_UNSOLVED),
    _task(4007, _BUG, Pick.EDITED_UNSOLVED),
    _task(3111, _FEATURE, Pick.SOLVED_AT_75),
    _task(3436, _FEATURE, Pick.EDITED_UNSOLVED),
    _task(4067, _FEATURE, Pick.EDITED_UNSOLVED),
    _task(4276, _FEATURE, Pick.EDITED_UNSOLVED),
    _task(4533, _FEATURE, Pick.EDITED_UNSOLVED),
    _task(1551, _FEATURE, Pick.UNSOLVED_NO_EDIT),
    _task(4087, _FEATURE, Pick.UNSOLVED_NO_EDIT),
    _task(4148, _FEATURE, Pick.UNSOLVED_NO_EDIT),
)


class SplitError(ValueError):
    """The split file is missing, empty or disagrees with the declared split."""


def evaluation_ids(path: Path) -> frozenset[str]:
    """The evaluation task ids from the committed split file; raises SplitError if it has none."""
    if not path.is_file():
        raise SplitError(f"no split file at {path}: declare the split before building lessons")
    ids = frozenset(entry["task"] for entry in json.loads(path.read_text())["evaluation"])
    if not ids:
        raise SplitError(f"{path} lists no evaluation tasks")
    return ids
