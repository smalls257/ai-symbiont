"""Which trainer a machine runs the night on, and the exact arguments it is given.

MLX on Apple Silicon, torch on an NVIDIA GPU, otherwise a refusal naming what is missing: a 1B
model is never trained on the CPU. The numbers are train_lora.sh's shared LoRA recipe and
plug_r4_combo.sh's 3 epochs; `scripts/routea/train_lora_torch.py` copies the same mlx-lm schedule.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

BATCH = 4
EPOCHS = 3  # plug_r4_combo.sh EPOCHS default
MAX_SEQ = 1024  # plug_r4_combo.sh LORA_MAX_LENGTH: the judge's rows carry a situation and a lesson
SEED = 0
RANK = 16
ALPHA = 32  # mlx scale 2.0 at rank 16, as peft spells it
TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
PEAK_LR = "1.0e-4"
END_LR = "1.0e-6"
FULL_WARMUP = 20
MIN_ITERS = 1


class Backend(StrEnum):
    """Where the 1B judge trains: the Apple GPU through mlx-lm, or an NVIDIA GPU through torch."""

    MLX = "mlx"
    TORCH_CUDA = "torch-cuda"


class NoTrainingHardwareError(RuntimeError):
    """This machine has no accelerator the nightly can train on; the message says what to do."""


class TooFewRowsError(ValueError):
    """The rows cannot fill one update, so a run would be silently empty."""


def choose_backend(system: str, machine: str, *, has_nvidia: bool) -> Backend:
    """MLX on Apple Silicon, torch on CUDA, otherwise refuse (never the CPU).

    `system` and `machine` are `platform.system()` and `platform.machine()`; `has_nvidia` is
    whether `nvidia-smi` lists a GPU. Raises NoTrainingHardwareError.
    """
    if system == "Darwin" and machine == "arm64":
        return Backend.MLX
    if has_nvidia:
        return Backend.TORCH_CUDA
    raise NoTrainingHardwareError(
        f"no accelerator to train on ({system} {machine}, no NVIDIA GPU found). The nightly trains "
        "on an Apple Silicon Mac (mlx) or an NVIDIA GPU (torch + CUDA). It will not train a 1B "
        "model on the CPU; run it on a machine that has one."
    )


def iterations(rows: int, epochs: int = EPOCHS) -> int:
    """Updates for `epochs` passes over `rows`, as train_lora.sh counts them (batch 4).

    Raises TooFewRowsError when the rows cannot fill one update.
    """
    count = rows * epochs // BATCH
    if count < MIN_ITERS:
        raise TooFewRowsError(f"{rows} rows x {epochs} epochs cannot fill a batch of {BATCH}")
    return count


def warmup_for(iters: int) -> int:
    """Warmup updates of a short run: a fifth of it under 100 updates, else 20 (train_lora.sh)."""
    return iters // 5 if iters < 100 else FULL_WARMUP


def mlx_lora_config(iters: int) -> str:
    """The mlx-lm LoRA config as YAML, the recipe of `scripts/routea/train_lora.sh`.

    mlx-lm adapts every linear layer of a Llama decoder block by default, which is what the torch
    trainer's `TARGETS` list names; the config therefore sets no `keys`.
    """
    return f"""fine_tune_type: lora
num_layers: -1
batch_size: {BATCH}
learning_rate: {PEAK_LR}
mask_prompt: true
max_seq_length: {MAX_SEQ}
steps_per_report: 20
steps_per_eval: 100000
save_every: 100000
seed: {SEED}
lr_schedule:
  name: cosine_decay
  warmup: {warmup_for(iters)}
  warmup_init: 1.0e-6
  arguments: [{PEAK_LR}, {iters}, {END_LR}]
lora_parameters:
  rank: {RANK}
  scale: 2.0
  dropout: 0.0
"""


@dataclass(frozen=True)
class TrainJob:
    """One training run: the fixed base, the rows' folder, how long, and where the adapter goes."""

    base: Path
    data: Path
    iters: int
    adapter: Path
    config: Path


def mlx_command(job: TrainJob) -> list[str]:
    """The arguments after `python` for `-m mlx_lm lora` on the job (adapter lands in the job)."""
    return [
        "-m",
        "mlx_lm",
        "lora",
        "-c",
        str(job.config),
        "--model",
        str(job.base),
        "--train",
        "--data",
        str(job.data),
        "--iters",
        str(job.iters),
        "--adapter-path",
        str(job.adapter),
    ]


def torch_command(script: Path, job: TrainJob) -> list[str]:
    """The arguments after `python` for the torch trainer: nightly recipe, fresh (no --resume)."""
    return [
        str(script),
        "--model",
        str(job.base),
        "--data",
        str(job.data),
        "--iters",
        str(job.iters),
        "--seed",
        str(SEED),
        "--recipe",
        "nightly",
        "--adapter",
        str(job.adapter),
    ]


def torch_environment() -> dict[str, str]:
    """What the torch trainer reads: the CUDA device and the training window."""
    return {"LCAP_DEVICE": "cuda", "LORA_MAX_LENGTH": str(MAX_SEQ)}


def peft_config(base: Path) -> dict[str, object]:
    """`adapter_config.json` for an mlx-trained adapter converted to PEFT tensors.

    The judge server loads PEFT adapters; mlx-lm's own config would not load there.
    """
    return {
        "base_model_name_or_path": str(base),
        "bias": "none",
        "fan_in_fan_out": False,
        "inference_mode": True,
        "lora_alpha": ALPHA,
        "lora_dropout": 0.0,
        "peft_type": "LORA",
        "r": RANK,
        "target_modules": list(TARGETS),
        "task_type": None,
        "use_dora": False,
    }
