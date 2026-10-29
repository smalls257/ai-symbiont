"""Check every chat row fits the training window under a real chat template; print counts only.

Usage (in the MLX venv outside the repo, which has `transformers` for tokenizers):
    python scripts/aidev/check_tokens.py --model <local model dir> --max-tokens 512 FILE.jsonl ...

Periphery. A row longer than `max_seq_length` is truncated by the trainer without a word, so the
habit's check sentence (the row's end) would be cut off. Any row over the limit makes this exit 1,
naming the file and row number.
"""

import argparse
import json
import sys
from pathlib import Path


def row_tokens(tokenizer, row: dict) -> int:
    """Tokens of one row once the model's chat template is applied."""
    text = tokenizer.apply_chat_template(row["messages"], tokenize=False)
    return len(tokenizer(text, add_special_tokens=False)["input_ids"])


def main() -> int:
    """Count tokens per row; exit 1 if any row exceeds the limit."""
    from transformers import AutoTokenizer  # noqa: PLC0415  (only in the MLX venv)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    over = []
    longest = 0
    for path in args.files:
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            count = row_tokens(tokenizer, json.loads(line))
            longest = max(longest, count)
            if count > args.max_tokens:
                over.append(f"{path.name}:{number} has {count} tokens")
    print(json.dumps({"longest_row_tokens": longest, "rows_over_limit": len(over)}))
    for finding in over:
        print(finding, file=sys.stderr)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
