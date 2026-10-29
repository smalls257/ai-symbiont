"""Answer questions that each carry their own system prompt, with one model load (MLX venv).

Usage: venv/bin/python answer_contexts.py --model M [--adapter A] --questions Q.jsonl --out O.jsonl

Each row holds `question_id`, `text` and `context` (the system prompt: e.g. one situation item's
lessons). Decoding is answer_questions.py's: greedy, MAX_TOKENS, the fixed template date, the whole
answer folded onto one line. A row without a context raises; counts and seconds go to stderr.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from mlx_lm import generate, load

sys.path.insert(0, str(Path(__file__).resolve().parent))

from answer_questions import MAX_TOKENS, TEMPLATE_DATE, _one_line  # noqa: E402


def answer_rows(model_path: str, adapter: str | None, rows: list[dict]) -> list[str]:
    """Greedy one-line answers, in row order, each under its own system prompt."""
    model, tokenizer = load(model_path, adapter_path=adapter)
    answers = []
    for row in rows:
        messages = [
            {"role": "system", "content": row["context"]},
            {"role": "user", "content": row["text"]},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, date_string=TEMPLATE_DATE
        )
        answers.append(_one_line(generate(model, tokenizer, prompt, max_tokens=MAX_TOKENS)))
    return answers


def main() -> None:
    """Answer every row and write one answer per question id."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.questions.read_text().splitlines()]
    started = time.monotonic()
    answers = answer_rows(args.model, args.adapter, rows)
    with args.out.open("w", encoding="utf-8") as fh:
        for row, answer in zip(rows, answers, strict=True):
            fh.write(json.dumps({"question_id": row["question_id"], "answer": answer}) + "\n")
    print(f"answered={len(answers)} seconds={time.monotonic() - started:.1f}", file=sys.stderr)


if __name__ == "__main__":
    main()
