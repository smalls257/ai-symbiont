"""Convert an mlx-lm LoRA adapter file to PEFT tensors, for CUDA answers with laptop weights.

Usage: python mlx_adapter_to_peft.py --mlx adapters.safetensors --out adapter_model.safetensors
mlx-lm stores `<module>.lora_a` as (in, r) and `.lora_b` as (r, out); PEFT stores
`base_model.model.<module>.lora_A.weight` as (r, in) and `lora_B.weight` as (out, r). Pair it with
an adapter_config.json of the same rank, alpha and targets (a CUDA-trained adapter has one).
"""

import argparse
from pathlib import Path

import numpy as np

PEFT_PREFIX = "base_model.model."
SIDES = {"lora_a": "lora_A", "lora_b": "lora_B"}


def peft_entry(name: str, tensor: np.ndarray) -> tuple[str, np.ndarray]:
    """PEFT key and transposed tensor for one mlx-lm LoRA tensor. Raises KeyError on other names."""
    module, _, side = name.rpartition(".")
    if side not in SIDES:
        raise KeyError(f"{name} is not an mlx-lm LoRA tensor")
    return f"{PEFT_PREFIX}{module}.{SIDES[side]}.weight", np.ascontiguousarray(tensor.T)


def main() -> None:
    from safetensors.numpy import load_file, save_file  # noqa: PLC0415  (desktop and uv envs)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mlx", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    converted = dict(peft_entry(k, v) for k, v in load_file(args.mlx).items())
    save_file(converted, args.out)
    print(f"{len(converted)} tensors")


if __name__ == "__main__":
    main()
