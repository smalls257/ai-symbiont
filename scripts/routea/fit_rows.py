"""Drop training rows that do not fit, counting each reason (MLX venv; a real chat template).

Usage (MLX venv): python fit_rows.py --model M --rows DIR [--max-tokens 512] [--max-answer 96]

A row longer than the training window is cut by the trainer without a word, and a target longer
than the answer budget can never be produced at test time; both are dropped here and counted in
DIR/fit.json, never truncated. train.jsonl is rewritten in place; valid.jsonl is its first 8 rows.
"""

import argparse
import json
from pathlib import Path

VALID_ROWS = 8


def tokens(tokenizer, text: str) -> int:
    """Tokens of plain text, without special tokens."""
    return len(tokenizer(text, add_special_tokens=False)["input_ids"])


def row_tokens(tokenizer, row: dict) -> int:
    """Tokens of the whole row under the model's chat template."""
    text = tokenizer.apply_chat_template(row["messages"], tokenize=False)
    return tokens(tokenizer, text)


def fit(tokenizer, rows: list[dict], max_tokens: int, max_answer: int) -> tuple[list[dict], dict]:
    """The rows that fit, and the count dropped for each reason."""
    kept, dropped = [], {"row_over_window": 0, "answer_over_budget": 0}
    for row in rows:
        if tokens(tokenizer, row["messages"][-1]["content"]) > max_answer:
            dropped["answer_over_budget"] += 1
        elif row_tokens(tokenizer, row) > max_tokens:
            dropped["row_over_window"] += 1
        else:
            kept.append(row)
    return kept, dropped


def main() -> None:
    """Rewrite DIR/train.jsonl with the rows that fit; write DIR/fit.json."""
    from transformers import AutoTokenizer  # noqa: PLC0415  (only in the MLX venv)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--max-answer", type=int, default=96)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    rows = [json.loads(line) for line in (args.rows / "train.jsonl").read_text().splitlines()]
    kept, dropped = fit(tokenizer, rows, args.max_tokens, args.max_answer)
    lines = "".join(json.dumps(row) + "\n" for row in kept)
    (args.rows / "train.jsonl").write_text(lines)
    (args.rows / "valid.jsonl").write_text("".join(json.dumps(r) + "\n" for r in kept[:VALID_ROWS]))
    report = {"rows_in": len(rows), "rows_kept": len(kept), **dropped}
    (args.rows / "fit.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
