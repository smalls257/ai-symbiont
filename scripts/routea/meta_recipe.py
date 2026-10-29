"""Reptile over LoRA weights, and the test cells it is judged on (METALORA). Pure: no torch.

The meta start counts only if it beats a blank start on the same recipe, lessons and steps, so
both arms run one cell list; the outer update is the first-order rule of Nichol et al. 2018
("On First-Order Meta-Learning Algorithms") with its step size annealed linearly to zero.
"""

from collections.abc import Sequence

import numpy as np

# Inner loop: a short constant-lr fine-tune of the LCAP adapter (rank 16, all linear layers) on one
# repo's lessons. 1e-4 is LCAP's peak lr; constant because Reptile's inner loops are short.
INNER_LR = 1.0e-4
EPOCHS = 8  # LCAP's budget: 8 passes over a set's rows (6 rows per lesson, batch 4)
ROWS_PER_LESSON = 6
BATCH = 4
SHORT_ITERS = (0, 8, 15, 30)  # the "fewer steps" axis, below LCAP's full budget
# Lessons taught per held-out repo. The dispatch asked for 5, 10 and 30, but no test repo holds
# more than 13 distinct lessons [measured], so the sizes are 3, 5 and 10: the "fewer lessons"
# question lives at the small end anyway.
SIZES = (3, 5, 10)


def full_budget(lessons: int) -> int:
    """LCAP's iteration count for a set of `lessons`: EPOCHS passes over its rows."""
    return lessons * ROWS_PER_LESSON * EPOCHS // BATCH


def cells(sizes: Sequence[int]) -> list[tuple[int, int]]:
    """(lessons taught, training iterations) for every size: the short budgets then LCAP's full
    one, deduplicated and ordered. Iterations 0 is the start itself, before any lesson."""
    return sorted({(size, iters) for size in sizes for iters in (*SHORT_ITERS, full_budget(size))})


def outer_step(iteration: int, iterations: int, first: float) -> float:
    """Reptile's outer step size at 0-based `iteration`, annealed linearly from `first` to 0."""
    if not 0 <= iteration < iterations:
        raise ValueError(f"iteration {iteration} outside 0..{iterations - 1}")
    return first * (1.0 - iteration / iterations)


def interpolate(start, adapted, step: float):
    """The shared start moved `step` of the way toward the weights one domain adapted to."""
    return start + step * (adapted - start)


def domain_order(domains: Sequence[str], iterations: int, seed: int) -> list[str]:
    """Which domain each outer iteration adapts to: shuffled full passes, so every meta-training
    repo is visited equally often and none dominates the start."""
    rng = np.random.RandomState(seed)
    picked: list[str] = []
    while len(picked) < iterations:
        picked += [domains[i] for i in rng.permutation(len(domains))]
    return picked[:iterations]


def taught(ids: Sequence[str], size: int) -> list[str]:
    """The first `size` lesson ids of a repo (sets nest); raises ValueError when it holds fewer."""
    if len(ids) < size:
        raise ValueError(f"repo holds {len(ids)} lessons, {size} asked")
    return list(ids[:size])
