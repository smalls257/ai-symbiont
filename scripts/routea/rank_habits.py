"""Habits kept by ranked choice: which kind's check sentence does the model find most likely?

Usage (MLX venv): python rank_habits.py --model M [--adapter A] --questions Q --system S --out O

For each habit question the five kinds' check sentences (`aidev/lessons.CHECK`) are scored as the
assistant reply by mean log-likelihood per reply token; nothing is generated, so answer length
cannot inflate the score. A tie for first is a miss (`plug.ranked_hit`); chance is one in five.
"""

import argparse
import json
import sys
from pathlib import Path

import mlx.core as mx
from mlx_lm import load

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parent / "aidev"))  # appended: routea's `lessons` must win

from answer_questions import TEMPLATE_DATE  # noqa: E402
from plug import ranked_hit  # noqa: E402

CHECKS_MODULE = HERE.parent / "aidev" / "lessons.py"


def checks() -> dict[str, str]:
    """The five kinds' check sentences, read from the AIDev lessons module by kind value."""
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("aidev_lessons", CHECKS_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {kind.value: text for kind, text in module.CHECK.items()}


def mean_reply_logprob(model, prompt: list[int], reply: list[int]) -> float:
    """Mean log-probability of the reply tokens after the prompt."""
    tokens = mx.array(prompt + reply)[None]
    logits = model(tokens[:, :-1])[0]
    logprobs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
    targets = mx.array(reply)
    picked = logprobs[len(prompt) - 1 :][mx.arange(len(reply)), targets]
    return float(mx.mean(picked))


def rank_all(model, tokenizer, questions: list[dict], system: str) -> list[dict]:
    """One row per question: each kind's score and whether its own kind ranked first."""
    sentences = checks()
    replies = {
        kind: tokenizer.encode(text, add_special_tokens=False) for kind, text in sentences.items()
    }
    rows = []
    for question in questions:
        prompt = tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": question["text"]}],
            add_generation_prompt=True,
            date_string=TEMPLATE_DATE,
        )
        scores = {kind: mean_reply_logprob(model, prompt, reply) for kind, reply in replies.items()}
        hit = ranked_hit(question["kind"], scores)
        rows.append({"question_id": question["question_id"], "hit": hit, "scores": scores})
    return rows


def main() -> None:
    """Rank every question and print the hit rate."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    model, tokenizer = load(args.model, adapter_path=args.adapter)
    questions = [json.loads(line) for line in args.questions.read_text().splitlines()]
    rows = rank_all(model, tokenizer, questions, args.system.read_text())
    args.out.write_text("".join(json.dumps(row) + "\n" for row in rows))
    hits = sum(row["hit"] for row in rows)
    print(
        json.dumps({"questions": len(rows), "hits": hits, "hit_rate": round(hits / len(rows), 4)})
    )


if __name__ == "__main__":
    main()
