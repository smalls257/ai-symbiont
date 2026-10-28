"""Train Route A's memory model on a project's new lessons, then forget the lessons.

Violation prevented: **Silent Fallback** on three edges. The export is the fail-closed
`lessons_for_memory_model` (one private lesson raises, never a shorter list). A failed training
run stops before `forget_trained`, so no lesson is deleted that the weights did not take in.
An adapter trained on one base model is never continued on another (`model.txt`).

Layout under --memory-dir (outside the repo; `symbiont serve --memory-dir` reads it):
`adapter/` (the LoRA, continued run after run), `manifests/` (ids and counts per training run,
written by `forget_trained`), `model.txt` (the base model), `logs/`. Training rows hold lesson
text, so they are deleted once the adapter has them. Prints counts only.

    uv run python scripts/routea/train_memory.py --data-dir ~/.symbiont --project demo \
        --memory-dir ~/symbiont-runs/routea/memory
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

from symbiont.core.memory_note import SYSTEM, training_pairs
from symbiont.miner.lessons import Lesson
from symbiont.service.memory_model import DEFAULT_MEMORY_MODEL
from symbiont.store.local import SparkPrivacyViolationError, Store
from symbiont.store.training import lessons_for_memory_model

HERE = Path(__file__).resolve().parent
LCAP_VENV = Path.home() / "symbiont-runs" / "lcap" / "venv"
VALID_ROWS = 8  # mlx-lm needs a valid split; it only reports loss, so a sample of train is enough
SEED = 0
# A handful of lessons gives a few dozen rows; LCAP's 8 passes left small sets underfit.
EPOCHS = 24


class TrainingRefusedError(RuntimeError):
    """Training cannot start or did not finish; nothing was forgotten."""


def chat_rows(project: str, lessons: list[Lesson]) -> list[dict[str, object]]:
    """mlx-lm chat rows: the live prompt for each lesson's trouble and its three-part line."""
    rows = []
    for lesson in lessons:
        for pair in training_pairs(project, lesson):
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": pair.prompt},
                {"role": "assistant", "content": pair.line},
            ]
            rows.append({"messages": messages})
    random.Random(SEED).shuffle(rows)
    return rows


def _write_rows(work: Path, rows: list[dict[str, object]]) -> None:
    work.mkdir(parents=True, exist_ok=True)
    for name, chosen in (("train", rows), ("valid", rows[:VALID_ROWS])):
        lines = "".join(json.dumps(row) + "\n" for row in chosen)
        (work / f"{name}.jsonl").write_text(lines, encoding="utf-8")


def _claim_base_model(memory_dir: Path, model: str) -> None:
    marker = memory_dir / "model.txt"
    if marker.exists() and marker.read_text().strip() != model:
        raise TrainingRefusedError(
            f"{memory_dir} holds an adapter for {marker.read_text().strip()}, not {model}"
        )
    memory_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(model + "\n")


def train(args: argparse.Namespace) -> dict[str, object]:
    """Export, train, forget; returns counts. Raises TrainingRefusedError, forgetting nothing."""
    store = Store.open(args.data_dir / "store.db")
    lessons = lessons_for_memory_model(store, args.project)
    if not lessons:
        raise TrainingRefusedError(f"no untrained lessons for {args.project}; mine first")
    _claim_base_model(args.memory_dir, args.model)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    work = args.memory_dir / "work" / stamp
    rows = chat_rows(args.project, lessons)
    _write_rows(work, rows)
    started = time.monotonic()
    command = [str(args.trainer), str(args.python), args.model, str(work)]
    command += [str(args.memory_dir / "adapter"), str(args.memory_dir / "logs"), stamp]
    env = os.environ | {"LORA_EPOCHS": str(args.epochs), "LORA_RESUME": "1"}
    finished = subprocess.run(["/usr/bin/env", *command], env=env, check=False)
    shutil.rmtree(work)
    if finished.returncode != 0:
        raise TrainingRefusedError(f"training failed (exit {finished.returncode}); see logs/")
    manifest = args.memory_dir / "manifests" / f"{stamp}.json"
    forgotten = store.forget_trained(args.project, manifest, exported=lessons)
    return {
        "lessons_trained": len(lessons),
        "training_rows": len(rows),
        "lessons_forgotten": forgotten,
        "train_seconds": round(time.monotonic() - started, 1),
        "model": args.model,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--memory-dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MEMORY_MODEL)
    parser.add_argument("--python", type=Path, default=LCAP_VENV / "bin" / "python")
    parser.add_argument("--trainer", type=Path, default=HERE / "train_lora.sh")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    args = parser.parse_args()
    args.data_dir, args.memory_dir = args.data_dir.expanduser(), args.memory_dir.expanduser()
    try:
        counts = train(args)
    except (TrainingRefusedError, SparkPrivacyViolationError) as refused:
        print(f"train_memory: {refused}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
