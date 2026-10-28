"""The T46 options and how each picks its setting on TRAIN folds (exploratory).

A setting is picked on four folds of TRAIN tasks and counted on the fifth. Options A and B
pick the setting with the highest value per step on the training folds; option C picks the
loosest threshold that conformal risk control allows. Pure numpy.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from symbiont.eval.note_cost_options import (
    EVERY_STEP,
    FP_HEADS,
    FP_WARN,
    SESSIONS,
    STEPS,
    Tiers,
    TierValues,
    Value,
    budgeted,
    per_step_value,
    spell_value,
    tiered_value,
)
from symbiont.eval.note_delivery import DeliveryRule, Gate

FOLDS = 5
WARNING_COST = 0.5  # T36's c: a false warning costs half a true one
HEADS_UP_COST = 0.25  # the brief's cheap tier
HEADS_UP_GAIN = 0.75  # a hypothesis: a quiet note helps less than a warning, but more than half
NOTES_PER_SESSION = 2  # option A's budget
BUDGETS = (1, 2, 3)  # option C
RISK_BOUND = 0.25  # option C: expected false notes per session at most a quarter of the budget
PRIMARY = "a_tiers_boundary_budget"

Chooser = Callable[[np.ndarray], tuple[int, float]]  # train counts -> (setting, score)


def gain_per_step(value: Value, stack: np.ndarray) -> np.ndarray:
    """Value per step of each setting, summed over the tasks in `stack`."""
    totals = stack.sum(axis=1)
    result: np.ndarray = value(totals) / totals[:, STEPS]
    return result


def by_value(value: Value) -> Chooser:
    """The setting with the highest TRAIN value per step; silence (index 0) unless one beats 0."""

    def choose(stack: np.ndarray) -> tuple[int, float]:
        """Setting with the best per-step value; silence when none is above 0."""
        gain = gain_per_step(value, stack)
        best = int(np.argmax(gain))  # first maximum: settings run from fewest notes to most
        return (best, float(gain[best])) if gain[best] > 0 else (0, 0.0)

    return choose


def by_risk_control(budget: int, bound: float) -> Chooser:
    """Conformal risk control over tasks: loosest threshold with false notes in budget."""

    def choose(stack: np.ndarray) -> tuple[int, float]:
        """Loosest setting whose bounded task risk stays within `bound`."""
        false_notes = stack[..., FP_WARN] + stack[..., FP_HEADS]
        loss = np.maximum.accumulate(false_notes / (budget * stack[..., SESSIONS]), axis=0)
        n_tasks = loss.shape[1]
        risk = n_tasks / (n_tasks + 1) * loss.mean(axis=1) + 1 / (n_tasks + 1)
        allowed = np.flatnonzero(risk <= bound)
        best = int(allowed[-1]) if len(allowed) else 0
        return best, float(gain_per_step(per_step_value(WARNING_COST), stack)[best])

    return choose


@dataclass(frozen=True)
class Option:
    """One way to deliver, price and pick notes."""

    key: str
    rule: DeliveryRule
    tiers: Tiers
    value: Value
    choose: Chooser


def _priced(key: str, rule: DeliveryRule, value: Value, tiers: Tiers = Tiers.ONE) -> Option:
    """An option whose settings are chosen by value."""
    return Option(key, rule, tiers, value, by_value(value))


def _tiered(key: str, heads_gain: float) -> Option:
    """A two-tier option with the given heads-up gain."""
    tiers = TierValues(1.0, WARNING_COST, heads_gain, HEADS_UP_COST)
    rule = budgeted(Gate.BOUNDARY, NOTES_PER_SESSION)
    return _priced(key, rule, tiered_value(tiers), Tiers.TWO)


def _risk_controlled(budget: int) -> Option:
    """An option that bounds false notes per session by risk control."""
    rule = budgeted(Gate.EVERY_STEP, budget)
    chooser = by_risk_control(budget, RISK_BOUND)
    return Option(f"c_budget_{budget}", rule, Tiers.ONE, per_step_value(WARNING_COST), chooser)


def catalog() -> list[Option]:
    """T36's per-step rule for reference, then A (primary), its parts, B, C and A's sensitivity."""
    a_rule = budgeted(Gate.BOUNDARY, NOTES_PER_SESSION)
    return [
        _priced("t36_per_step", EVERY_STEP, per_step_value(WARNING_COST)),
        _tiered(PRIMARY, HEADS_UP_GAIN),
        _priced("a_one_tier_boundary_budget", a_rule, per_step_value(WARNING_COST)),
        _priced("b_per_spell", EVERY_STEP, spell_value(WARNING_COST)),
        *[_risk_controlled(k) for k in BUDGETS],
        _tiered("a_heads_up_gain_0.5", 0.5),
        _tiered("a_heads_up_gain_1", 1.0),
    ]


def task_folds(n_tasks: int, seed: int) -> np.ndarray:
    """Fold of each task (tasks in sorted order): a seeded shuffle dealt round-robin."""
    folds = np.empty(n_tasks, dtype=np.int64)
    folds[np.random.default_rng(seed).permutation(n_tasks)] = np.arange(n_tasks) % FOLDS
    return folds


def cross_validate(
    blocks: Sequence[np.ndarray], folds: np.ndarray, choose: Chooser
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Held-out counts per task and the (block, setting) picked per fold."""
    return cross_validate_per_fold({fold: blocks for fold in range(FOLDS)}, folds, choose)


def cross_validate_per_fold(
    blocks_by_fold: Mapping[int, Sequence[np.ndarray]], folds: np.ndarray, choose: Chooser
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """As `cross_validate`, with its own blocks per outer fold."""
    held = np.zeros(blocks_by_fold[0][0].shape[1:])
    picked = []
    for fold in range(FOLDS):
        blocks, inside = blocks_by_fold[fold], folds != fold
        picks = [choose(block[:, inside]) for block in blocks]
        block = max(range(len(blocks)), key=lambda index: (picks[index][1], -index))
        held[~inside] = blocks[block][picks[block][0], ~inside]
        picked.append((block, picks[block][0]))
    return held, picked
