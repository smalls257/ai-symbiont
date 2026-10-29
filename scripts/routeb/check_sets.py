"""Render every Route B row and question with Glimmer's own tokenizer and count tokens. CPU only.

The dry run's data check: a row the template cannot split, or one longer than the trainer accepts,
stops here instead of hours into a GPU job. Writes token-stats.json (counts only) beside the data.

Usage: python check_sets.py --snapshot GLIMMER_HF_SNAPSHOT --data WORK/data
"""

import argparse
import json
from pathlib import Path
from statistics import mean

from glimmer_chat import prompt_ids, row_ids
from lora_schedule import Budget
from transformers import AutoTokenizer

MAX_ROW_TOKENS = 512  # LCAP's max_seq_length; a longer row would be cut, so it is refused
SIZES = ("one-10", "one-30", "one-100")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def train_stats(tokenizer, train_file: Path) -> dict[str, object]:
    """Row lengths, answer tokens and steps for one training set; raises on an overlong row."""
    split = [row_ids(tokenizer, row) for row in _jsonl(train_file)]
    lengths = [len(prompt) + len(answer) for prompt, answer in split]
    if max(lengths) > MAX_ROW_TOKENS:
        raise ValueError(f"{train_file}: a row has {max(lengths)} tokens, over {MAX_ROW_TOKENS}")
    budget = Budget()
    return {
        "rows": len(split),
        "steps": budget.steps(len(split)),
        "row_tokens_mean": round(mean(lengths), 1),
        "row_tokens_max": max(lengths),
        "answer_tokens_mean": round(mean(len(answer) for _, answer in split), 1),
        "tokens_per_epoch": sum(lengths),
    }


def ask_stats(tokenizer, questions: Path, system: str) -> dict[str, object]:
    """Prompt lengths for one question file under one system turn."""
    lengths = [
        len(
            prompt_ids(
                tokenizer,
                [{"role": "system", "content": system}, {"role": "user", "content": q["text"]}],
            )
        )
        for q in _jsonl(questions)
    ]
    return {
        "questions": len(lengths),
        "prompt_tokens_mean": round(mean(lengths), 1),
        "prompt_tokens_max": max(lengths),
    }


def stats(tokenizer, data: Path) -> dict[str, object]:
    """Token counts for every training set and every arm's prompts."""
    memory = (data / "context" / "memory.txt").read_text(encoding="utf-8")
    found: dict[str, object] = {}
    for size in SIZES:
        ceiling = (data / "context" / f"{size}.txt").read_text(encoding="utf-8")
        found[size] = {
            "train": train_stats(tokenizer, data / "train" / size / "train.jsonl"),
            "ask_memory": ask_stats(tokenizer, data / "ask" / f"{size}.jsonl", memory),
            "ask_ceiling": ask_stats(tokenizer, data / "ask" / f"{size}.jsonl", ceiling),
            "ask_para_memory": ask_stats(tokenizer, data / "ask-para" / f"{size}.jsonl", memory),
        }
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.snapshot)
    found = stats(tokenizer, args.data)
    (args.data / "token-stats.json").write_text(json.dumps(found, indent=1))
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
