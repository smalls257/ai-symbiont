"""The train step's input: the rows the next adapter learns, where it starts, and a manifest.

FROM_SCRATCH (default, for evaluation honesty) trains every kept lesson from the start arm, so a
dropped lesson is gone; CONTINUED_WITH_REPLAY starts from the last adapter with the new rows plus
REPLAY_SHARE of the old, and names dropped lessons still in the weights. Rows over the domain's
cap are dropped and counted, never trimmed. The manifest holds ids and counts only. Pure.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from utility import Decision

REPLAY_SHARE = 0.3  # earlier rows replayed in continued mode; a third keeps old lessons in view
REPLAY_SEED = 0
SUCCESS_SOURCE = "success"  # lesson_id prefix of a verified-success row (situation to action)


class TrainMode(StrEnum):
    """How the next adapter relates to the last one."""

    FROM_SCRATCH = "from-scratch"
    CONTINUED_WITH_REPLAY = "continued-with-replay"


@dataclass(frozen=True)
class Row:
    """One chat row and where it came from: a lesson id, or `success:<attempt id>`."""

    lesson_id: str
    kind: str  # card, check, resolved, situation, success
    messages: tuple[dict[str, str], ...]

    def chars(self) -> int:
        """Characters in all turns; the length cap is checked on this before any tokenizer."""
        return sum(len(turn["content"]) for turn in self.messages)


@dataclass(frozen=True)
class PreviousTraining:
    """What the last adapter learned: its directory on the host and its rows' lesson ids."""

    adapter_dir: str
    lesson_ids: frozenset[str]
    row_keys: frozenset[str]


@dataclass(frozen=True)
class TrainingPlan:
    """The rows to train, where training starts, and the manifest that names them."""

    rows: tuple[Row, ...]
    start_from: str | None
    manifest: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanInputs:
    """Everything the plan is built from."""

    round_index: int
    decisions: Mapping[str, Decision]  # lesson id -> this round's decision
    lesson_rows: Mapping[str, Sequence[Row]]  # lesson id -> its rows, card row first
    success_rows: Sequence[Row]
    max_row_chars: int


def row_key(row: Row) -> str:
    """A stable short hash of a row's text: the manifest's way to name a row without its text."""
    return hashlib.sha256(json.dumps(row.messages, sort_keys=True).encode()).hexdigest()[:16]


def weighted_rows(decision: Decision, rows: Sequence[Row]) -> list[Row]:
    """All rows for KEEP and PROBATION, the card row only for DOWN_WEIGHT, none for DROP."""
    if decision is Decision.DROP:
        return []
    return list(rows[:1]) if decision is Decision.DOWN_WEIGHT else list(rows)


def _candidates(inputs: PlanInputs) -> list[Row]:
    lesson = [
        row
        for lesson_id, decision in sorted(inputs.decisions.items())
        for row in weighted_rows(decision, inputs.lesson_rows.get(lesson_id, ()))
    ]
    return lesson + list(inputs.success_rows)


def _replayed(rows: Sequence[Row], previous: PreviousTraining) -> list[Row]:
    """Rows new since the last adapter, plus REPLAY_SHARE of the rows it already learned."""
    new = [row for row in rows if row_key(row) not in previous.row_keys]
    old = [row for row in rows if row_key(row) in previous.row_keys]
    keep = round(len(old) * REPLAY_SHARE)
    return new + random.Random(REPLAY_SEED).sample(old, keep)


def plan_training(
    inputs: PlanInputs, mode: TrainMode, previous: PreviousTraining | None
) -> TrainingPlan:
    """The next adapter's rows and start; continued mode without a previous adapter starts fresh."""
    candidates = _candidates(inputs)
    fitting = [row for row in candidates if row.chars() <= inputs.max_row_chars]
    base = previous if mode is TrainMode.CONTINUED_WITH_REPLAY else None
    rows = _replayed(fitting, base) if base else fitting
    manifest = _manifest(inputs, mode, rows, base)
    manifest["rows_dropped_too_long"] = len(candidates) - len(fitting)
    return TrainingPlan(tuple(rows), base.adapter_dir if base else None, manifest)


def _by_decision(decisions: Mapping[str, Decision]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {str(d): [] for d in Decision}
    for lesson_id, decision in sorted(decisions.items()):
        found[str(decision)].append(lesson_id)
    return found


def _manifest(
    inputs: PlanInputs, mode: TrainMode, rows: Sequence[Row], base: PreviousTraining | None
) -> dict[str, Any]:
    """Ids and counts only: the audit record of one round's training set."""
    by_decision = _by_decision(inputs.decisions)
    dropped = set(by_decision[str(Decision.DROP)])
    keys = "".join(sorted(row_key(row) for row in rows))
    return {
        "round": inputs.round_index,
        "train_mode": str(mode),
        "starts_from_previous_adapter": base is not None,
        "lessons_by_decision": by_decision,
        "dropped_but_in_weights": sorted(dropped & base.lesson_ids) if base else [],
        "rows": len(rows),
        "rows_by_kind": dict(sorted(Counter(row.kind for row in rows).items())),
        "success_rows": sum(row.lesson_id.startswith(SUCCESS_SOURCE) for row in rows),
        "max_row_chars": inputs.max_row_chars,
        "row_keys_sha": hashlib.sha256(keys.encode()).hexdigest()[:16],
    }
