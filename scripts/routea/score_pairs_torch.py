"""Score judge queries on a CUDA GPU: P(yes) for each (situation, lesson) pair (desktop LCAP venv).

Usage: python score_pairs_torch.py --model M [--adapter A] -q QUERIES.jsonl -o SCORES.jsonl

Each row holds `question_id`, `context` and `text`. The score is the softmax of the next-token
logits over the single tokens "yes" and "no" after the assistant header, so no text is generated.
A model whose "yes" or "no" is not one token raises. Counts and seconds go to stderr, never text.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from answer_questions_torch import TEMPLATE_DATE, _loaded
from train_lora_torch import DEVICE
from transformers import AutoTokenizer

BATCH = 16


def single_token(tokenizer, word: str) -> int:
    """The token id of `word`; raises if the tokenizer splits it."""
    ids = tokenizer.encode(word, add_special_tokens=False)
    if len(ids) != 1:
        raise ValueError(f"{word!r} is {len(ids)} tokens for this tokenizer, not one")
    return ids[0]


def prompt_of(tokenizer, row: dict) -> list[int]:
    """The row's tokens up to the assistant's first token."""
    return tokenizer.apply_chat_template(
        [{"role": "system", "content": row["context"]}, {"role": "user", "content": row["text"]}],
        add_generation_prompt=True,
        date_string=TEMPLATE_DATE,
        tokenize=True,
        return_dict=False,
    )


@torch.no_grad()
def yes_probability(model, tokenizer, prompts: list[list[int]], yes: int, no: int) -> list[float]:
    """P(yes) against P(no) at the next token of each left-padded prompt."""
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    width = max(len(p) for p in prompts)
    ids = torch.tensor([[pad] * (width - len(p)) + p for p in prompts], device=DEVICE)
    mask = torch.tensor([[0] * (width - len(p)) + [1] * len(p) for p in prompts], device=DEVICE)
    logits = model(input_ids=ids, attention_mask=mask).logits[:, -1, :]
    pair = torch.stack([logits[:, yes], logits[:, no]], dim=-1).float().softmax(dim=-1)
    return pair[:, 0].tolist()


def main() -> None:
    """Score every query and write one P(yes) per question id."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("-q", "--questions", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    yes, no = single_token(tokenizer, "yes"), single_token(tokenizer, "no")
    model = _loaded(args.model, args.adapter)
    rows = [json.loads(line) for line in args.questions.read_text().splitlines()]
    started = time.monotonic()
    scores: list[float] = []
    for start in range(0, len(rows), BATCH):
        chunk = [prompt_of(tokenizer, row) for row in rows[start : start + BATCH]]
        scores += yes_probability(model, tokenizer, chunk, yes, no)
    with args.out.open("w", encoding="utf-8") as fh:
        for row, score in zip(rows, scores, strict=True):
            fh.write(json.dumps({"question_id": row["question_id"], "p_yes": score}) + "\n")
    print(f"scored={len(scores)} seconds={time.monotonic() - started:.1f}", file=sys.stderr)


if __name__ == "__main__":
    main()
