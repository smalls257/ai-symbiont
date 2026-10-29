"""Plug round 2's trainer backend: MLX on the laptop or CUDA (PyTorch + PEFT) on the 5080 desktop.

Usage: python plug_r2_backend.py check BACKEND  |  python plug_r2_backend.py iters ROWS [EPOCHS]

The CUDA trainer (`train_lora_torch.py`) copies the MLX recipe and gave identical recall from the
same weights (`.superpowers/sdd/2026-10-27-ai-symbiont-build-plan/plug-cuda-report.md`). An unknown
backend raises, so a typo never falls back to the default machine.
"""

import sys
from enum import StrEnum
from pathlib import Path

BATCH = 4  # train_lora.sh and train_lora_torch.py


class TrainerBackend(StrEnum):
    """Where a variant trains and answers."""

    MLX = "mlx"
    CUDA = "cuda"


def backend_of(value: str) -> TrainerBackend:
    """The backend named by `value`; raises ValueError naming the known ones."""
    try:
        return TrainerBackend(value)
    except ValueError as exc:
        known = ", ".join(member.value for member in TrainerBackend)
        raise ValueError(f"unknown TRAINER_BACKEND {value!r}; known: {known}") from exc


def iters_for(rows: int, epochs: int = 1) -> int:
    """Optimizer steps for `epochs` passes, as train_lora.sh computes them."""
    steps = rows * epochs // BATCH
    if steps <= 0:
        raise ValueError(f"{rows} rows give no training step at batch {BATCH}")
    return steps


def main() -> None:
    """`check` validates a backend; `iters` prints the step count for a rows file."""
    stage, value, *rest = sys.argv[1:]
    if stage == "check":
        print(backend_of(value).value)
    elif stage == "iters":
        rows = len(Path(value).read_text().splitlines())
        print(iters_for(rows, int(rest[0]) if rest else 1))
    else:
        raise SystemExit(f"unknown stage {stage}; use check or iters")


if __name__ == "__main__":
    main()
