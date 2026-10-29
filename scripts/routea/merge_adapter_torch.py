"""Merge a LoRA adapter into its base model and save the result, so round 4's nightly adapters can
start from one fixed judge rather than from plain weights or yesterday's adapter.

Usage (desktop venv): python merge_adapter_torch.py --model M --adapter A --out DIR
"""

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    base = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.bfloat16)
    merged = PeftModel.from_pretrained(base, args.adapter).merge_and_unload()
    merged.save_pretrained(args.out)
    AutoTokenizer.from_pretrained(args.model).save_pretrained(args.out)
    print(f"merged {args.adapter.name} into {args.out}")


if __name__ == "__main__":
    main()
