"""Teach each held-out repo's lessons from a given start, then answer its held-out questions.

Runs in the desktop LCAP venv. Violation prevented: **Paper Tiger**. Every start (blank, Reptile
meta, joint) is trained by the LCAP recipe (`learning_rate`, `batch_order`, fresh Adam) on the same
lessons for the same iterations and asked the same questions, beside a floor (base model) and a
ceiling (the taught lessons in the prompt). One process keeps the base model loaded and resets the
LoRA weights per cell, so a cell costs its own training and answering only. Each cell prints arm,
repo index, size, iterations and seconds (never text); finished cells are skipped on resume.

    venv/bin/python adapt_answer_torch.py --model M --data DATA --split test --out answers/ \
        --start floor --start ceiling --start blank --start meta=starts/r/start.pt [--cells 5:15]
"""

import argparse
import json
import time
from pathlib import Path

import torch
from answer_questions_torch import BATCH as ANSWER_BATCH
from answer_questions_torch import TOKEN_BUDGET, _generate, _one_line, _prompts
from meta_recipe import SIZES, cells, taught
from meta_train_torch import encoded, fit, load_weights, snapshot
from mlx_lora_recipe import learning_rate
from train_lora_torch import DEVICE, SEED, lora_model, peak_bytes
from transformers import AutoTokenizer

QUESTION_SETS = {"template": "questions.jsonl", "paraphrase": "questions-para.jsonl"}
REFERENCES = ("floor", "ceiling")  # starts that are not adapters: base model, lessons in prompt


def slug(repo: str) -> str:
    return repo.replace("/", "__")


def answers_for(model, tokenizer, questions: list[dict], context: str | None) -> list[dict]:
    """Greedy one-line answers, batched by prompt tokens as answer_questions_torch does."""
    if not questions:
        return []
    prompts = _prompts(tokenizer, questions, context)
    size = max(1, min(ANSWER_BATCH, TOKEN_BUDGET // max(len(p) for p in prompts)))
    texts: list[str] = []
    for start in range(0, len(prompts), size):
        texts += [_one_line(t) for t in _generate(model, tokenizer, prompts[start : start + size])]
    return [
        {"question_id": q["question_id"], "answer": t}
        for q, t in zip(questions, texts, strict=True)
    ]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(".part")
    scratch.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    scratch.rename(path)  # a cell exists only once both of its files are whole


def _asked(questions: dict[str, list[dict]], lesson_ids: list[str]) -> dict[str, list[dict]]:
    wanted = set(lesson_ids)
    return {name: [q for q in rows if q["lesson_id"] in wanted] for name, rows in questions.items()}


class HeldOutRun:
    """The loaded model, one held-out split's lessons and questions, and where answers go."""

    def __init__(self, args) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(args.model)
        self.model = lora_model(args.model)
        self.blank = snapshot(self.model)
        self.out = args.out
        self.repos = json.loads((args.data / "domains.json").read_text())[args.split]
        self.contexts = json.loads((args.data / "contexts.json").read_text())
        self.questions = {
            name: [json.loads(line) for line in (args.data / file).read_text().splitlines()]
            for name, file in QUESTION_SETS.items()
        }
        self.rows = _rows_by_lesson(self.tokenizer, args.data)

    def _answer_cell(self, path: Path, lesson_ids: list[str], context: str | None) -> None:
        for name, asked in _asked(self.questions, lesson_ids).items():
            _write(
                path.with_name(f"{name}-{path.name}"),
                answers_for(self.model, self.tokenizer, asked, context),
            )

    def reference(self, arm: str, repo: str, size: int) -> None:
        """Floor (no adapter, no lessons) or ceiling (the taught lessons in the prompt)."""
        path = self.out / arm / slug(repo) / f"{size}.jsonl"
        if path.with_name(f"paraphrase-{path.name}").exists():
            return
        context = self.contexts[repo][str(size)] if arm == "ceiling" else None
        with self.model.disable_adapter():
            self._answer_cell(path, taught(self.repos[repo], size), context)

    def adapted(self, arm: str, start: dict, repo: str, cell: tuple[int, int]) -> float:
        """Train `start` on the repo's first `size` lessons for `iters`, then answer; seconds."""
        size, iters = cell
        path = self.out / arm / slug(repo) / f"{size}-{iters}.jsonl"
        if path.with_name(f"paraphrase-{path.name}").exists():
            return 0.0
        began = time.monotonic()
        load_weights(self.model, start)
        ids = taught(self.repos[repo], size)
        rows = [row for lesson_id in ids for row in self.rows[lesson_id]]
        if iters:
            fit(
                self.model,
                rows,
                iters,
                seed=SEED,
                lr_at=lambda update: learning_rate(update, iters),
            )
        trained = time.monotonic() - began
        self._answer_cell(path, ids, None)
        return trained


def _rows_by_lesson(tokenizer, data: Path) -> dict[str, list]:
    by_lesson: dict[str, list] = {}
    for line in (data / "rows.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        by_lesson.setdefault(row["lesson_id"], []).append(encoded(tokenizer, row["messages"]))
    return by_lesson


def _starts(specs: list[str], blank: dict) -> dict[str, dict | None]:
    """Arm name -> LoRA start weights (None for the floor and ceiling references)."""
    starts: dict[str, dict | None] = {}
    for spec in specs:
        name, _, path = spec.partition("=")
        if name in REFERENCES:
            starts[name] = None
        else:
            starts[name] = torch.load(path, map_location=DEVICE) if path else blank
    return starts


def _cells(spec: str | None) -> list[tuple[int, int]]:
    if not spec:
        return cells(SIZES)
    return [tuple(int(n) for n in item.split(":")) for item in spec.split(",")]  # type: ignore[misc]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--split", choices=["val", "test"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--start", action="append", required=True, help="floor, ceiling, blank, NAME=start.pt"
    )
    parser.add_argument("--cells", help="SIZE:ITERS,... (default: every size x every budget)")
    args = parser.parse_args()
    run = HeldOutRun(args)
    starts = _starts(args.start, run.blank)
    plan = _cells(args.cells)
    for index, repo in enumerate(sorted(run.repos)):
        for arm, start in starts.items():
            began = time.monotonic()
            _run_arm(run, (arm, start), repo, plan)
            print(f"arm {arm} repo {index} seconds {time.monotonic() - began:.0f}", flush=True)
    print(f"{peak_bytes()} peak memory footprint", flush=True)


def _run_arm(run: HeldOutRun, arm: tuple[str, dict | None], repo: str, plan: list) -> None:
    name, start = arm
    if start is None:
        for size in sorted({size for size, _ in plan}):
            run.reference(name, repo, size)
        return
    trained = sum(run.adapted(name, start, repo, cell) for cell in plan)
    print(f"arm {name} train_s {trained:.0f}", flush=True)


if __name__ == "__main__":
    main()
