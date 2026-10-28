"""Answer LCAP held-out questions with a local MLX model, optionally with an adapter or the lessons.

Runs in the LCAP venv (`~/symbiont-runs/lcap/venv`, mlx-lm), not the repo env, so it imports
nothing from `symbiont`. Violation prevented: **Black Box**. Every run writes one answer row per
question plus a timing line to stderr (counts and seconds, never prompt or answer text), so a
slow or empty arm is visible without reading answers.

    venv/bin/python answer_questions.py --model M --questions ask/one-10.jsonl --out ans.jsonl \
        [--adapter adapters/one-10] [--context context/one-10.txt]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from mlx_lm import batch_generate, load

SYSTEM = "You are a memory model. Answer in one line of plain prose, naming exact commands."
MAX_TOKENS = 96  # one line of prose with a command fits; longer answers are cut at the newline
BATCH = 16


def _prompts(tokenizer, questions: list[dict], context: str | None) -> list[list[int]]:
    system = context if context is not None else SYSTEM
    return [
        tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": q["text"]}],
            add_generation_prompt=True,
        )
        for q in questions
    ]


def _first_line(text: str) -> str:
    stripped = text.strip()
    return stripped.splitlines()[0] if stripped else ""


def answer_all(model_path: str, adapter: str | None, questions: list[dict], context: str | None):
    """Greedy one-line answers, in question order."""
    model, tokenizer = load(model_path, adapter_path=adapter)
    prompts = _prompts(tokenizer, questions, context)
    answers: list[str] = []
    for start in range(0, len(prompts), BATCH):
        batch = batch_generate(
            model, tokenizer, prompts[start : start + BATCH], max_tokens=MAX_TOKENS
        )
        answers += [_first_line(text) for text in batch.texts]
    return answers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--context", type=Path)
    args = parser.parse_args()
    questions = [json.loads(line) for line in args.questions.read_text().splitlines()]
    context = args.context.read_text() if args.context else None
    started = time.monotonic()
    answers = answer_all(args.model, args.adapter, questions, context)
    seconds = time.monotonic() - started
    if len(answers) != len(questions):
        raise RuntimeError(f"{len(answers)} answers for {len(questions)} questions")
    with args.out.open("w", encoding="utf-8") as fh:
        for question, answer in zip(questions, answers, strict=True):
            fh.write(json.dumps({"question_id": question["question_id"], "answer": answer}) + "\n")
    empty = sum(1 for answer in answers if not answer)
    print(f"answered={len(answers)} empty={empty} seconds={seconds:.1f}", file=sys.stderr)


if __name__ == "__main__":
    main()
