"""The options of T46 as per-task counts over a grid of thresholds (exploratory, TRAIN only).

Each option is a delivery rule (which steps may carry a note, how many, how far apart) and a
value (what a note earns and costs). For every threshold setting this module counts, per task:
true and false notes in the warning and heads-up tiers, trouble spells hit, steps, spells and
sessions. Selection and scoring live in `note_cost_report`. Pure numpy over traces.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from symbiont.eval.note_delivery import (
    COOLDOWN_STEPS,
    NO_SPELL,
    DeliveryRule,
    Gate,
    NoteTrace,
    note_steps,
    spell_ids,
)

NEVER = float("inf")
# Columns of a per-task counts matrix.
TP_WARN, FP_WARN, TP_HEADS, FP_HEADS, SPELLS_HIT, STEPS, SPELLS, SESSIONS = range(8)
N_COLUMNS = 8
# Upper-tail shares of eligible steps that set the threshold grid: the T36 fly warned on
# 0.06% of steps at c = 0.5 and 37% at c = 0.25, so the grid is dense in the far tail.
GRID_SHARES = tuple(np.geomspace(1e-4, 1.0, 40).tolist())


@dataclass(frozen=True)
class Session:
    """One session as arrays, with its spells numbered across the whole arm."""

    task: int
    step_risk: np.ndarray
    followed: np.ndarray
    boundary: np.ndarray
    spell: np.ndarray


@dataclass(frozen=True)
class Prepared:
    """An arm's traces as arrays, the task ids in a fixed order and per-task totals."""

    tasks: tuple[str, ...]
    sessions: tuple[Session, ...]
    totals: np.ndarray  # (tasks, N_COLUMNS), only STEPS, SPELLS and SESSIONS filled
    spell_task: np.ndarray  # task index of each spell id


def prepare(traces: Sequence[NoteTrace], tasks: Sequence[str]) -> Prepared:
    """Turn traces into arrays; `tasks` fixes the row order shared by every arm."""
    index = {task: i for i, task in enumerate(tasks)}
    sessions, spell_task, offset = [], [], 0
    totals = np.zeros((len(tasks), N_COLUMNS))
    for trace in traces:
        task = index[trace.task_id]
        local = spell_ids(trace.followed)
        n_spells = int(local.max()) + 1 if len(local) else 0
        spell = np.where(local == NO_SPELL, NO_SPELL, local + offset)
        offset += n_spells
        spell_task += [task] * n_spells
        totals[task, [STEPS, SPELLS, SESSIONS]] += (len(trace.step_risk), n_spells, 1)
        arrays = (
            np.asarray(trace.step_risk),
            np.asarray(trace.followed),
            np.asarray(trace.boundary),
        )
        sessions.append(Session(task, *arrays, spell))
    return Prepared(tuple(tasks), tuple(sessions), totals, np.asarray(spell_task, dtype=np.int64))


@dataclass(frozen=True)
class Shown:
    """Every note one rule showed at one threshold, flattened across sessions."""

    task: np.ndarray
    step_risk: np.ndarray
    followed: np.ndarray
    spell: np.ndarray


def shown(arm: Prepared, threshold: float, rule: DeliveryRule) -> Shown:
    """Spend notes session by session under `rule` at `threshold`."""
    parts = []
    for s in arm.sessions:
        eligible = (
            s.boundary if rule.gate is Gate.BOUNDARY else np.ones(len(s.step_risk), dtype=bool)
        )
        steps = note_steps(s.step_risk, eligible, threshold, rule)
        parts.append(
            (np.full(len(steps), s.task), s.step_risk[steps], s.followed[steps], s.spell[steps])
        )
    if not parts:
        raise ValueError("an arm with no sessions cannot show notes")
    return Shown(*(np.concatenate([p[i] for p in parts]) for i in range(4)))


def counts(arm: Prepared, notes: Shown, warn_at: float) -> np.ndarray:
    """Per-task counts; a note whose risk reaches `warn_at` is a warning, else a heads-up."""
    matrix = arm.totals.copy()
    warn = notes.step_risk >= warn_at
    for column, mask in (
        (TP_WARN, warn & notes.followed),
        (FP_WARN, warn & ~notes.followed),
        (TP_HEADS, ~warn & notes.followed),
        (FP_HEADS, ~warn & ~notes.followed),
    ):
        np.add.at(matrix[:, column], notes.task[mask], 1)
    hit = np.unique(notes.spell[notes.spell != NO_SPELL])
    np.add.at(matrix[:, SPELLS_HIT], arm.spell_task[hit], 1)
    return matrix


def threshold_grid(arm: Prepared, gate: Gate) -> list[float]:
    """NEVER first, then thresholds from strict to loose: fewer notes come first."""
    risks = np.concatenate(
        [s.step_risk[s.boundary] if gate is Gate.BOUNDARY else s.step_risk for s in arm.sessions]
    )
    cut = np.quantile(risks, 1.0 - np.asarray(GRID_SHARES), method="higher")
    return [NEVER, *sorted({float(c) for c in cut}, reverse=True)]


Setting = tuple[float, float]  # (note threshold, warning-tier threshold)


def single_tier(grid: Sequence[float]) -> list[Setting]:
    """Every note is a warning."""
    return [(t, t) for t in grid]


def two_tiers(grid: Sequence[float]) -> list[Setting]:
    """A note threshold and a stricter-or-equal warning threshold; NEVER warns on nothing."""
    return [(low, high) for i, low in enumerate(grid) for high in grid[: i + 1]]


class Tiers(StrEnum):
    """Whether notes come in one tier or two."""

    ONE = "warning only"
    TWO = "warning and heads-up"


@dataclass(frozen=True)
class Stack:
    """Per-task counts for each setting, (settings, tasks, N_COLUMNS), and the settings."""

    counts: np.ndarray
    settings: tuple[Setting, ...]


def count_stack(arm: Prepared, rule: DeliveryRule, tiers: Tiers) -> Stack:
    """Counts for each setting; one delivery pass per note threshold.

    Settings run from fewest notes to most, NEVER first, so index 0 is always silence.
    """
    grid = threshold_grid(arm, rule.gate)
    settings = two_tiers(grid) if tiers is Tiers.TWO else single_tier(grid)
    cache: dict[float, Shown] = {}
    layers = []
    for low, high in settings:
        if low not in cache:
            cache[low] = shown(arm, low, rule)
        layers.append(counts(arm, cache[low], high))
    return Stack(np.stack(layers), tuple(settings))


Value = Callable[[np.ndarray], np.ndarray]  # summed counts (..., N_COLUMNS) -> net value


def per_step_value(cost: float) -> Value:
    """T36: every true note gains 1, every false note costs `cost`."""
    return lambda sums: (
        sums[..., TP_WARN] + sums[..., TP_HEADS] - cost * (sums[..., FP_WARN] + sums[..., FP_HEADS])
    )


def spell_value(cost: float) -> Value:
    """Option B: a spell with a note gains 1 once; every false note costs `cost`."""
    return lambda sums: sums[..., SPELLS_HIT] - cost * (sums[..., FP_WARN] + sums[..., FP_HEADS])


@dataclass(frozen=True)
class TierValues:
    """What a true note gains and a false one costs, per tier."""

    warn_gain: float
    warn_cost: float
    heads_gain: float
    heads_cost: float


def tiered_value(tiers: TierValues) -> Value:
    """Option A: warnings and heads-ups priced separately."""

    def value(sums: np.ndarray) -> np.ndarray:
        warn = tiers.warn_gain * sums[..., TP_WARN] - tiers.warn_cost * sums[..., FP_WARN]
        heads = tiers.heads_gain * sums[..., TP_HEADS] - tiers.heads_cost * sums[..., FP_HEADS]
        return warn + heads

    return value


EVERY_STEP = DeliveryRule(Gate.EVERY_STEP)


def budgeted(gate: Gate, budget: int) -> DeliveryRule:
    """At most `budget` notes per session, none within the cooldown of the last."""
    return DeliveryRule(gate, budget=budget, cooldown=COOLDOWN_STEPS)
