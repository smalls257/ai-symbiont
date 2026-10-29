"""The laptop's mlx-lm LoRA recipe for LCAP, restated without mlx so a CUDA trainer can follow it.

Violation prevented: **Paper Tiger**. The 3B rows train on a CUDA GPU (transformers + peft) while
the 1B rows train on MLX. If the port changed the learning-rate curve, the batch order or which
tokens carry loss, a 1B-vs-3B gap could be a trainer gap dressed as a model-size gap. Each
function below copies one piece of mlx-lm 0.32.2 (named in its docstring), and the tests pin the
numbers, so both trainers run one recipe. Pure: no torch, no clock, no files.
"""

import math

import numpy as np

# run_lcap.sh's lora_yaml: peak 1e-4, 20 warmup iters from 1e-6, cosine decay to 1e-6.
PEAK_LR = 1.0e-4
WARMUP = 20
WARMUP_INIT = 1.0e-6
END_LR = 1.0e-6
PAD_TO = 32  # mlx-lm iterate_batches pads each batch to one plus a multiple of 32
MAX_SEQ = 512  # run_lcap.sh max_seq_length


def learning_rate(update: int, iters: int) -> float:
    """lr of 0-based optimizer update `update`: mlx-lm build_schedule's join of a linear warmup
    and cosine_decay(PEAK_LR, iters, END_LR), joined at WARMUP + 1 as mlx-lm does."""
    if update < WARMUP + 1:
        return min(update, WARMUP) * ((PEAK_LR - WARMUP_INIT) / WARMUP) + WARMUP_INIT
    step = min(update - (WARMUP + 1), iters)
    return END_LR + 0.5 * (1.0 + math.cos(math.pi / iters * step)) * (PEAK_LR - END_LR)


def batch_order(lengths: list[int], batch: int, iters: int, seed: int) -> list[list[int]]:
    """Row indices of each of `iters` batches, as mlx-lm iterate_batches yields them: rows sorted
    by token length, cut into whole batches (a short tail is dropped), batches visited in a fresh
    numpy permutation (legacy global seeding) every pass. Raises ValueError on too few rows."""
    if len(lengths) < batch:
        raise ValueError(f"{len(lengths)} rows cannot fill one batch of {batch}")
    order = sorted(range(len(lengths)), key=lengths.__getitem__)
    batches = [order[i : i + batch] for i in range(0, len(order) - batch + 1, batch)]
    rng = np.random.RandomState(seed)
    picked: list[list[int]] = []
    while len(picked) < iters:
        picked += [batches[i] for i in rng.permutation(len(batches))]
    return picked[:iters]


def padded_width(lengths: list[int]) -> int:
    """Token width of one batch array (mlx-lm iterate_batches)."""
    return min(1 + PAD_TO * ((max(lengths) + PAD_TO - 1) // PAD_TO), MAX_SEQ)


def loss_span(offset: int, length: int, width: int) -> range:
    """Target positions that carry loss in a batch array `width` tokens wide (inputs drop the last
    column, targets drop the first). mlx-lm default_loss keeps step s = t + 1 when
    offset <= s <= length, so the completion counts, and so does the one pad target right after
    it (token id 0); both trainers keep that quirk so their losses match."""
    return range(max(offset - 1, 0), min(length, width - 1))
