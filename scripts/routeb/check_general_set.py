"""Render the general sqlglot set with Glimmer's own tokenizer and count tokens. CPU only.

A row the chat template cannot split, or one over the trainer's 512 tokens, stops here instead
of in the GPU job. Also counts the prompt card's tokens. Writes token-stats.json beside the set.
Usage: python check_general_set.py --snapshot GLIMMER_HF_SNAPSHOT --work WORK
"""

import argparse
import json
from pathlib import Path

from check_sets import ask_stats, train_stats
from sqlglot_rows import MEMORY_SYSTEM
from transformers import AutoTokenizer

SET = "sqlglot-general"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.snapshot)
    card = (args.work / "card.txt").read_text(encoding="utf-8")
    found = {
        SET: train_stats(tokenizer, args.work / "train" / SET / "train.jsonl"),
        "held_out": ask_stats(tokenizer, args.work / "questions.jsonl", MEMORY_SYSTEM),
        "card_tokens": len(tokenizer(card)["input_ids"]),
    }
    (args.work / "token-stats.json").write_text(json.dumps(found, indent=1))
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
