"""The laptop's mlx-lm LoRA recipe for LCAP, restated without mlx so a CUDA trainer can follow it.

The 3B rows train on CUDA, the 1B rows on MLX; a changed lr curve, batch order or loss mask would
dress a trainer gap as a model-size gap. Each function copies one piece of mlx-lm 0.32.2 (named in
its docstring) and the tests pin the numbers. Pure: no torch, no clock, no files.
"""

import math
import os

import numpy as np

# run_lcap.sh's lora_yaml: peak 1e-4, 20 warmup iters from 1e-6, cosine decay to 1e-6.
PEAK_LR = 1.0e-4
WARMUP = 20
WARMUP_INIT = 1.0e-6
END_LR = 1.0e-6
PAD_TO = 32  # mlx-lm iterate_batches pads each batch to one plus a multiple of 32
# run_lcap.sh max_seq_length; LORA_MAX_LENGTH overrides it, as in train_lora.sh (round 2: 1024).
MAX_SEQ = int(os.environ.get("LORA_MAX_LENGTH", "512"))


def warmup_for(iters: int) -> int:
    """Warmup updates of a per-repo run (train_lora.sh): a fifth of a short run, else 20.

    The nightly update is short (60 to 240 iters); keeping the LCAP 20 would warm up for a third
    of a 60-iter run and change its curve against the laptop's."""
    return iters // 5 if iters < 100 else WARMUP


def epoch_iters(rows: int, epochs: int, batch: int) -> int:
    """Updates for `epochs` passes over `rows`, as train_lora.sh and run_lcap.sh count them.

    Raises ValueError when the rows cannot fill one update, so a run is never silently empty."""
    iters = rows * epochs // batch
    if iters < 1:
        raise ValueError(
            f"too few rows: {rows} rows x {epochs} epochs cannot fill a batch of {batch}"
        )
    return iters


def learning_rate(update: int, iters: int, warmup: int = WARMUP) -> float:
    """lr of 0-based optimizer update `update`: mlx-lm build_schedule's join of a linear warmup
    and cosine_decay(PEAK_LR, iters, END_LR), joined at warmup + 1 as mlx-lm does."""
    if update < warmup + 1:
        return min(update, warmup) * ((PEAK_LR - WARMUP_INIT) / warmup) + WARMUP_INIT
    step = min(update - (warmup + 1), iters)
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
    """Target positions carrying loss in a `width`-token batch (mlx-lm default_loss).

    Keeps offset <= t + 1 <= length: the completion and the one pad target after it, a quirk both
    trainers keep so their losses match."""
    return range(max(offset - 1, 0), min(length, width - 1))
