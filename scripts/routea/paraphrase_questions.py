"""Paraphrase LCAP held-out questions with the base model: a second, freer held-out set.

Runs in the LCAP venv (mlx-lm), not the repo env. A paraphrase that drops the repo name or a
backticked command no longer asks about its lesson; it is dropped and counted, never replaced by
the template wording, so every kept question is still answerable. Prints counts only.
Usage: venv/bin/python paraphrase_questions.py --model M --data <lcap data dir>
"""

import argparse
import json
import sys
from pathlib import Path

from mlx_lm import batch_generate, load
from paraphrase_rules import keeps_details

INSTRUCTION = (
    "Reword the question below so it asks for the same thing in different words. "
    "Keep the repository name and every part inside backticks exactly as written. "
    "Reply with the reworded question only, on one line.\n\nQuestion: "
)
MAX_TOKENS = 80
BATCH = 32
TEMPLATE_DATE = "26 Jul 2024"  # fixed so reruns produce the same prompts


def _paraphrases(model_path: str, texts: list[str]) -> list[str]:
    model, tokenizer = load(model_path)
    prompts = [
        tokenizer.apply_chat_template(
            [{"role": "user", "content": INSTRUCTION + text}],
            add_generation_prompt=True,
            date_string=TEMPLATE_DATE,
        )
        for text in texts
    ]
    out: list[str] = []
    for start in range(0, len(prompts), BATCH):
        batch = batch_generate(
            model, tokenizer, prompts[start : start + BATCH], max_tokens=MAX_TOKENS
        )
        out += [(text.strip().splitlines() or [""])[0].strip().strip('"') for text in batch.texts]
    return out


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    lessons = {row["lesson_id"]: row for row in _jsonl(args.data / "lessons.jsonl")}
    questions = _jsonl(args.data / "questions.jsonl")
    reworded = _paraphrases(args.model, [q["text"] for q in questions])
    kept = []
    for question, text in zip(questions, reworded, strict=True):
        lesson = lessons[question["lesson_id"]]
        if keeps_details(question["text"], text, lesson["repo"], lesson["file"]):
            kept.append({**question, "question_id": question["question_id"] + "p", "text": text})
    _write(args.data / "questions-para.jsonl", kept)
    by_lesson = {q["lesson_id"] for q in kept}
    for ask in sorted((args.data / "ask").glob("*.jsonl")):
        wanted = {q["lesson_id"] for q in _jsonl(ask)}
        _write(args.data / "ask-para" / ask.name, [q for q in kept if q["lesson_id"] in wanted])
    counts = {"asked": len(questions), "kept": len(kept), "lessons_covered": len(by_lesson)}
    print(json.dumps(counts), file=sys.stderr)
    (args.data / "para-counts.json").write_text(json.dumps(counts))


if __name__ == "__main__":
    main()
