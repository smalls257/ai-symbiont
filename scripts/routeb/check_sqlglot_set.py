"""Render the sqlglot sets with Glimmer's own tokenizer and count tokens. CPU only, no weights.

Every row goes through `glimmer_chat.row_ids`, so a row the template cannot split into prompt and
answer, or one over the trainer's 512 tokens, stops here instead of hours into a GPU job. Writes
token-stats.json (counts only) beside the sets.

Usage: python check_sqlglot_set.py --snapshot GLIMMER_HF_SNAPSHOT --work WORK
"""

import argparse
import json
from pathlib import Path

from check_sets import ask_stats, train_stats
from sqlglot_rows import MEMORY_SYSTEM
from transformers import AutoTokenizer

SETS = ("sqlglot-own", "sqlglot-all")


def stats(tokenizer, work: Path) -> dict[str, object]:
    """Row lengths and steps per set, and the held-out questions' prompt lengths."""
    found: dict[str, object] = {
        name: train_stats(tokenizer, work / "train" / name / "train.jsonl") for name in SETS
    }
    found["held_out"] = ask_stats(tokenizer, work / "questions.jsonl", MEMORY_SYSTEM)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.snapshot)
    found = stats(tokenizer, args.work)
    (args.work / "token-stats.json").write_text(json.dumps(found, indent=1))
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
