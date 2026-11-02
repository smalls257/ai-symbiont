"""Plug round 4 combo pass, GPU side: one nightly adapter read at several adapter scales.

Usage (desktop venv): python plug_r4_combo_gpu.py --model BASE --adapter A --queries Q \
--habit-questions HQ --habit-system HS --out DIR --scales 0.5 0.6 ...

Scaling the LoRA deltas at read time is the habit fix (no retraining); 1.0 is as trained.
"""

import argparse
import json
import sys
from pathlib import Path

from answer_questions_torch import _loaded
from rank_habits_torch import rank_all
from score_pairs_torch import BATCH, prompt_of, single_token, yes_probability
from transformers import AutoTokenizer


class NoLoraLayersError(RuntimeError):
    """The adapter exposed no scalable LoRA layer."""


def scalable_layers(model) -> list[tuple[dict, float]]:
    """Each LoRA layer's scaling dict with its trained value."""
    found = [
        (m.scaling, m.scaling["default"])
        for m in model.modules()
        if isinstance(getattr(m, "scaling", None), dict) and "default" in m.scaling
    ]
    if not found:
        raise NoLoraLayersError("no module with a LoRA scaling dict")
    return found


def set_scale(layers: list[tuple[dict, float]], factor: float) -> None:
    """Scale every LoRA delta to `factor` times its trained strength."""
    for scaling, trained in layers:
        scaling["default"] = trained * factor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--habit-questions", type=Path, required=True)
    parser.add_argument("--habit-system", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scales", type=float, nargs="+", required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    yes, no = single_token(tokenizer, "yes"), single_token(tokenizer, "no")
    model = _loaded(args.model, args.adapter)
    layers = scalable_layers(model)
    rows = [json.loads(line) for line in args.queries.read_text().splitlines()]
    prompts = [prompt_of(tokenizer, row) for row in rows]
    questions = [json.loads(x) for x in args.habit_questions.read_text().splitlines()]
    system = args.habit_system.read_text()
    for factor in args.scales:
        set_scale(layers, factor)
        scores: list[float] = []
        for start in range(0, len(prompts), BATCH):
            scores += yes_probability(model, tokenizer, prompts[start : start + BATCH], yes, no)
        folder = args.out / f"s{factor:g}"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "scores.jsonl").open("w", encoding="utf-8") as fh:
            for row, score in zip(rows, scores, strict=True):
                fh.write(json.dumps({"question_id": row["question_id"], "p_yes": score}) + "\n")
        habits = rank_all(model, tokenizer, questions, system)
        (folder / "habits.jsonl").write_text("".join(json.dumps(h) + "\n" for h in habits))
        print(
            f"scale={factor:g} scored={len(scores)} habits={sum(h['hit'] for h in habits)}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
