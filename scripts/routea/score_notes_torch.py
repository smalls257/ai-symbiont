"""Score a forced reply on a CUDA GPU: the model's mean log-probability per reply token (LCAP venv).

Usage: python score_notes_torch.py --model M [--adapter A] -q ROWS.jsonl -o SCORES.jsonl

Each row holds `question_id`, `context`, `text` and `reply`. The score is the mean log-probability
of the reply's tokens after the chat prompt, as rank_habits.py scores check sentences; nothing is
generated. Counts and seconds go to stderr, never text.
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
def mean_reply_logprob(model, prompt: list[int], reply: list[int]) -> float:
    """Mean log-probability of the reply tokens after the prompt."""
    tokens = torch.tensor([prompt + reply], device=DEVICE)
    logits = model(input_ids=tokens[:, :-1]).logits[0].float()
    logprobs = logits.log_softmax(dim=-1)[len(prompt) - 1 :]
    picked = logprobs[torch.arange(len(reply), device=DEVICE), torch.tensor(reply, device=DEVICE)]
    return float(picked.mean())


def main() -> None:
    """Score every row and write one mean log-probability per question id."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("-q", "--questions", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = _loaded(args.model, args.adapter)
    rows = [json.loads(line) for line in args.questions.read_text().splitlines()]
    started = time.monotonic()
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            reply = tokenizer.encode(row["reply"], add_special_tokens=False)
            score = mean_reply_logprob(model, prompt_of(tokenizer, row), reply)
            fh.write(json.dumps({"question_id": row["question_id"], "logprob": score}) + "\n")
    print(f"scored={len(rows)} seconds={time.monotonic() - started:.1f}", file=sys.stderr)


if __name__ == "__main__":
    main()
