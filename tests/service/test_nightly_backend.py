"""The trainer choice: Apple Silicon trains with mlx, NVIDIA with torch, nothing else.

Violation prevented: Silent Fallback. A machine with no accelerator raises; no test or code path
trains a 1B model on the CPU.
"""

from pathlib import Path

import pytest

from symbiont.service.nightly_backend import (
    BATCH,
    Backend,
    NoTrainingHardwareError,
    TooFewRowsError,
    TrainJob,
    choose_backend,
    iterations,
    mlx_command,
    mlx_lora_config,
    peft_config,
    torch_command,
    torch_environment,
    warmup_for,
)

JOB = TrainJob(Path("/b"), Path("/d"), 120, Path("/a"), Path("/c.yaml"))


def test_apple_silicon_trains_with_mlx_even_when_it_also_lists_nvidia():
    assert choose_backend("Darwin", "arm64", has_nvidia=False) is Backend.MLX
    assert choose_backend("Darwin", "arm64", has_nvidia=True) is Backend.MLX


@pytest.mark.parametrize("system", ["Linux", "Windows"])
def test_an_nvidia_gpu_trains_with_torch(system):
    assert choose_backend(system, "x86_64", has_nvidia=True) is Backend.TORCH_CUDA


@pytest.mark.parametrize(
    ("system", "machine"), [("Linux", "x86_64"), ("Windows", "AMD64"), ("Darwin", "x86_64")]
)
def test_no_accelerator_refuses_loudly_and_names_the_machine(system, machine):
    with pytest.raises(NoTrainingHardwareError, match=f"{system} {machine}.*CPU"):
        choose_backend(system, machine, has_nvidia=False)


def test_iterations_are_rows_times_epochs_over_the_batch_as_train_lora_counts_them():
    assert iterations(400) == 400 * 3 // BATCH
    assert iterations(100, epochs=8) == 200


def test_too_few_rows_to_fill_one_update_raises():
    with pytest.raises(TooFewRowsError):
        iterations(1)


def test_warmup_is_a_fifth_of_a_short_run_else_twenty():
    assert warmup_for(60) == 12
    assert warmup_for(99) == 19
    assert warmup_for(100) == 20


def test_the_mlx_config_carries_the_shared_recipe_for_this_run_length():
    config = mlx_lora_config(300)
    for line in (
        "learning_rate: 1.0e-4",
        "mask_prompt: true",
        "max_seq_length: 1024",
        "batch_size: 4",
        "warmup: 20",
        "arguments: [1.0e-4, 300, 1.0e-6]",
        "rank: 16",
        "scale: 2.0",
    ):
        assert line in config


def test_the_mlx_command_trains_from_the_fixed_base_with_no_resume():
    command = mlx_command(JOB)
    assert command[:3] == ["-m", "mlx_lm", "lora"]
    assert command[command.index("--model") + 1] == "/b"
    assert command[command.index("--adapter-path") + 1] == "/a"
    assert "--resume-adapter-file" not in command


def test_the_torch_command_uses_the_nightly_recipe_and_never_resumes():
    command = torch_command(Path("/s/train_lora_torch.py"), JOB)
    assert command[command.index("--recipe") + 1] == "nightly"
    assert "--resume" not in command
    assert torch_environment()["LCAP_DEVICE"] == "cuda"


def test_the_peft_config_matches_the_rank_alpha_and_targets_the_torch_trainer_uses():
    config = peft_config(Path("/b"))
    assert (config["r"], config["lora_alpha"]) == (16, 32)
    assert set(config["target_modules"]) == {
        "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
    }  # fmt: skip
