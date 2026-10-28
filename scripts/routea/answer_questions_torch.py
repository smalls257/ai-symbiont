"""Answer LCAP held-out questions on a CUDA GPU (transformers + peft), as the MLX script does.

Runs in the desktop LCAP venv, not the repo env. Violation prevented: **Black Box**. Every run
writes one answer row per question and one stderr line of counts and seconds (never prompt or
answer text), so a slow or empty arm is visible without reading answers. The prompts, the pinned
template date, greedy decoding, the 96-token cap and the first-line cut match the MLX script, so
the CUDA rows are scored by the same files and scorer.

    venv/bin/python answer_questions_torch.py --model M --questions ask/one-10.jsonl --out a.jsonl \
        [--adapter adapters/one-10] [--context context/one-10.txt]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

SYSTEM = "You are a memory model. Answer in one line of plain prose, naming exact commands."
MAX_TOKENS = 96  # as answer_questions.py
TEMPLATE_DATE = "26 Jul 2024"  # as answer_questions.py, so reruns and both machines match
BATCH = int(os.environ.get("LCAP_ANSWER_BATCH", "16"))
# Prompt tokens per batch: a 100-lesson ceiling prompt (several thousand tokens) runs a few at a
# time so its KV cache fits in 16 GB beside the 3B weights; short prompts run BATCH at a time.
TOKEN_BUDGET = int(os.environ.get("LCAP_ANSWER_TOKENS", "24000"))


def _prompts(tokenizer, questions: list[dict], context: str | None) -> list[list[int]]:
    system = context if context is not None else SYSTEM
    return [
        tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": q["text"]}],
            add_generation_prompt=True,
            date_string=TEMPLATE_DATE,
            tokenize=True,
            return_dict=False,
        )
        for q in questions
    ]


def _first_line(text: str) -> str:
    stripped = text.strip()
    return stripped.splitlines()[0] if stripped else ""


def _loaded(model_path: str, adapter: str | None):
    model = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.bfloat16).to("cuda")
    if adapter:
        model = PeftModel.from_pretrained(model, adapter)
    return model.eval()


@torch.no_grad()
def _generate(model, tokenizer, chunk: list[list[int]]) -> list[str]:
    """Greedy continuations of left-padded prompts, decoded without special tokens."""
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    width = max(len(p) for p in chunk)
    ids = torch.tensor([[pad] * (width - len(p)) + p for p in chunk], device="cuda")
    attention = torch.tensor([[0] * (width - len(p)) + [1] * len(p) for p in chunk], device="cuda")
    out = model.generate(
        input_ids=ids,
        attention_mask=attention,
        max_new_tokens=MAX_TOKENS,
        do_sample=False,
        temperature=None,
        top_p=None,
        pad_token_id=pad,
    )
    return tokenizer.batch_decode(out[:, width:], skip_special_tokens=True)


def answer_all(model_path: str, adapter: str | None, questions: list[dict], context: str | None):
    """Greedy one-line answers, in question order."""
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = _loaded(model_path, adapter)
    prompts = _prompts(tokenizer, questions, context)
    size = max(1, min(BATCH, TOKEN_BUDGET // max(len(p) for p in prompts)))
    answers: list[str] = []
    for start in range(0, len(prompts), size):
        texts = _generate(model, tokenizer, prompts[start : start + size])
        answers += [_first_line(text) for text in texts]
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
    print(f"{torch.cuda.max_memory_reserved()} peak memory footprint", file=sys.stderr)


if __name__ == "__main__":
    main()
