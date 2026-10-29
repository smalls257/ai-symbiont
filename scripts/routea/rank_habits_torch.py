"""Habits kept by ranked choice on a CUDA GPU: the torch twin of `rank_habits.py`.

Usage (desktop venv): python rank_habits_torch.py --model M [--adapter A] --questions Q \
--system S --out O

Same scoring as the MLX script: each kind's check sentence is the assistant reply, scored by mean
log-likelihood per reply token, nothing generated. A tie for first is a miss (`plug.ranked_hit`).
"""

import argparse
import json
import sys
from pathlib import Path

import torch
from answer_questions_torch import TEMPLATE_DATE, _loaded
from train_lora_torch import DEVICE
from transformers import AutoTokenizer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parent / "aidev"))  # appended: routea's `lessons` must win

from habit_checks import checks  # noqa: E402
from plug import ranked_hit  # noqa: E402


@torch.no_grad()
def mean_reply_logprob(model, prompt: list[int], reply: list[int]) -> float:
    """Mean log-probability of the reply tokens after the prompt."""
    ids = torch.tensor([prompt + reply], device=DEVICE)
    logits = model(input_ids=ids[:, :-1]).logits[0].float()
    logprobs = torch.log_softmax(logits, dim=-1)
    positions = torch.arange(len(prompt) - 1, len(prompt) + len(reply) - 1, device=DEVICE)
    picked = logprobs[positions, torch.tensor(reply, device=DEVICE)]
    return float(picked.mean())


def rank_all(model, tokenizer, questions: list[dict], system: str) -> list[dict]:
    """One row per question: each kind's score and whether its own kind ranked first."""
    replies = {
        kind: tokenizer.encode(text, add_special_tokens=False) for kind, text in checks().items()
    }
    rows = []
    for question in questions:
        prompt = tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": question["text"]}],
            add_generation_prompt=True,
            date_string=TEMPLATE_DATE,
            tokenize=True,
            return_dict=False,
        )
        scores = {kind: mean_reply_logprob(model, prompt, reply) for kind, reply in replies.items()}
        rows.append(
            {
                "question_id": question["question_id"],
                "hit": ranked_hit(question["kind"], scores),
                "scores": scores,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = _loaded(args.model, args.adapter)
    questions = [json.loads(line) for line in args.questions.read_text().splitlines()]
    rows = rank_all(model, tokenizer, questions, args.system.read_text())
    args.out.write_text("".join(json.dumps(row) + "\n" for row in rows))
    hits = sum(row["hit"] for row in rows)
    print(
        json.dumps({"questions": len(rows), "hits": hits, "hit_rate": round(hits / len(rows), 4)})
    )


if __name__ == "__main__":
    main()
