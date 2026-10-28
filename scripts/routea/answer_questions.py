"""Answer LCAP held-out questions with a local MLX model, optionally with an adapter or the lessons.

Runs in the LCAP venv (`~/symbiont-runs/lcap/venv`, mlx-lm), not the repo env, so it imports
nothing from `symbiont`. Violation prevented: **Black Box**. Every run writes one answer row per
question plus a timing line to stderr (counts and seconds, never prompt or answer text), so a
slow or empty arm is visible without reading answers.

    venv/bin/python answer_questions.py --model M --questions ask/one-10.jsonl --out ans.jsonl \
        [--adapter adapters/one-10] [--context context/one-10.txt]
"""

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

import mlx.core as mx
from mlx_lm import batch_generate, load
from mlx_lm.models.cache import make_prompt_cache

SYSTEM = "You are a memory model. Answer in one line of plain prose, naming exact commands."
# One line of prose with a command fits. The whole answer is kept, newlines folded to spaces:
# base Llama puts the command on the line after "The command that worked is:", and cutting at
# the first newline scored that as a miss [measured, 1B ceiling at 30 lessons].
MAX_TOKENS = 96
# Lower LCAP_ANSWER_BATCH if a long ceiling context runs out of memory.
BATCH = int(os.environ.get("LCAP_ANSWER_BATCH", "16"))
# Llama 3.x templates stamp today's date into the system turn; a fixed date keeps reruns identical.
TEMPLATE_DATE = "26 Jul 2024"


def _prompts(tokenizer, questions: list[dict], context: str | None) -> list[list[int]]:
    system = context if context is not None else SYSTEM
    return [
        tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": q["text"]}],
            add_generation_prompt=True,
            date_string=TEMPLATE_DATE,
        )
        for q in questions
    ]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _shared_prefix(prompts: list[list[int]]) -> int:
    """Tokens every prompt starts with, leaving at least one token of each prompt to feed."""
    shortest = min(len(p) for p in prompts)
    length = 0
    while length < shortest - 1 and all(p[length] == prompts[0][length] for p in prompts):
        length += 1
    return length


def _prefilled(model, prefix: list[int]):
    """A cache holding `prefix`: the ceiling arm's lessons are read once, not per question."""
    cache = make_prompt_cache(model)
    if prefix:
        model(mx.array(prefix)[None], cache=cache)
        mx.eval([c.state for c in cache])
    return cache


def answer_all(model_path: str, adapter: str | None, questions: list[dict], context: str | None):
    """Greedy one-line answers, in question order."""
    model, tokenizer = load(model_path, adapter_path=adapter)
    prompts = _prompts(tokenizer, questions, context)
    shared = _shared_prefix(prompts)
    cache = _prefilled(model, prompts[0][:shared])
    answers: list[str] = []
    for start in range(0, len(prompts), BATCH):
        chunk = [p[shared:] for p in prompts[start : start + BATCH]]
        caches = [copy.deepcopy(cache) for _ in chunk]
        batch = batch_generate(model, tokenizer, chunk, prompt_caches=caches, max_tokens=MAX_TOKENS)
        answers += [_one_line(text) for text in batch.texts]
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
