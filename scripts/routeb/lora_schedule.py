"""The arithmetic of a Route B LoRA run: prompt masking, batch order and the learning-rate curve.

Stdlib only, so the repo's tests check it and the Strix venv runs it unchanged. The schedule is
LCAP's (warmup then cosine decay, same epochs for every set size), so Glimmer's rows are trained
on the budget the stand-in and Llama rows were.
"""

import math
import random
from dataclasses import dataclass

IGNORED = -100  # label value the loss skips: prompt tokens are context, never targets


@dataclass(frozen=True)
class Budget:
    """LCAP's budget: same epochs for every size, so iters = rows * epochs / batch."""

    epochs: int = 8
    batch: int = 4
    peak_lr: float = 1e-4
    floor_lr: float = 1e-6
    warmup: int = 20

    def steps(self, rows: int) -> int:
        """Optimizer steps for `rows` training rows; raises when the set is too small to train."""
        total = rows * self.epochs // self.batch
        if total <= self.warmup:
            raise ValueError(f"{rows} rows give {total} steps, not more than the warmup")
        return total


def masked(prompt: list[int], answer: list[int]) -> tuple[list[int], list[int]]:
    """Input ids and labels: the loss reads only the answer tokens."""
    if not answer:
        raise ValueError("a training row needs at least one answer token")
    return prompt + answer, [IGNORED] * len(prompt) + answer


def batch_order(rows: int, budget: Budget, seed: int) -> list[list[int]]:
    """Row indices per step: each epoch a fresh seeded shuffle, cut into batches of `batch`."""
    flat: list[int] = []
    for epoch in range(budget.epochs):
        order = list(range(rows))
        random.Random(seed * 1000 + epoch).shuffle(order)
        flat += order
    steps = budget.steps(rows)
    return [flat[step * budget.batch : (step + 1) * budget.batch] for step in range(steps)]


def lr_at(step: int, total: int, budget: Budget) -> float:
    """Linear warmup from the floor to the peak, then cosine decay back to the floor."""
    if step < budget.warmup:
        return budget.floor_lr + (budget.peak_lr - budget.floor_lr) * step / budget.warmup
    progress = (step - budget.warmup) / max(1, total - budget.warmup)
    cosine = 0.5 * (1 + math.cos(math.pi * min(1.0, progress)))
    return budget.floor_lr + (budget.peak_lr - budget.floor_lr) * cosine


def padded(rows: list[tuple[list[int], list[int]]], pad_id: int) -> tuple[list, list, list]:
    """Right-padded ids, labels and attention mask for one batch."""
    width = max(len(ids) for ids, _ in rows)
    ids = [r_ids + [pad_id] * (width - len(r_ids)) for r_ids, _ in rows]
    labels = [r_labels + [IGNORED] * (width - len(r_labels)) for _, r_labels in rows]
    mask = [[1] * len(r_ids) + [0] * (width - len(r_ids)) for r_ids, _ in rows]
    return ids, labels, mask
