"""Answer rows that each carry their own system prompt, on a CUDA GPU (twin of answer_contexts.py).

Usage (desktop LCAP venv): python answer_contexts_torch.py --model M [--adapter A] -q Q -o O

Each row holds `question_id`, `text` and `context`. Decoding is answer_questions_torch.py's: greedy,
the 96-token cap, the fixed template date, one-line folding. A row without a context raises; one
stderr line gives counts and seconds, never prompt or answer text.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from answer_questions_torch import (
    BATCH,
    TEMPLATE_DATE,
    TOKEN_BUDGET,
    _generate,
    _loaded,
    _one_line,
)
from transformers import AutoTokenizer


def prompts_of(tokenizer, rows: list[dict]) -> list[list[int]]:
    """Each row's tokens under its own system prompt."""
    return [
        tokenizer.apply_chat_template(
            [
                {"role": "system", "content": row["context"]},
                {"role": "user", "content": row["text"]},
            ],
            add_generation_prompt=True,
            date_string=TEMPLATE_DATE,
            tokenize=True,
            return_dict=False,
        )
        for row in rows
    ]


def answer_rows(model_path: str, adapter: str | None, rows: list[dict]) -> list[str]:
    """Greedy one-line answers, in row order."""
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = _loaded(model_path, adapter)
    prompts = prompts_of(tokenizer, rows)
    size = max(1, min(BATCH, TOKEN_BUDGET // max(len(p) for p in prompts)))
    answers: list[str] = []
    for start in range(0, len(prompts), size):
        answers += [
            _one_line(t) for t in _generate(model, tokenizer, prompts[start : start + size])
        ]
    return answers


def main() -> None:
    """Answer every row and write one answer per question id."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("-q", "--questions", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
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
