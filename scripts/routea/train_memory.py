"""Train Route A's memory model on a project's new lessons, then forget the lessons.

The export is `lessons_for_memory_model` under the user's own-history consent, scrubbed of
credentials. A failed run stops before `forget_trained`; an adapter is never continued on another
base model. Under --memory-dir: `adapter/`, `manifests/`, `adapter.json` (base model and
provenance), `logs/`. Prints counts only.
Usage: uv run python scripts/routea/train_memory.py --data-dir ... --project demo --memory-dir ...
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
from symbiont.service.memory_model import DEFAULT_MEMORY_MODEL, AdapterProvenance
from symbiont.service.wiring import ADAPTER_RECORD
from symbiont.store.consent import ConsentFileError, read_consent
from symbiont.store.local import ForgetMismatchError, SparkPrivacyViolationError, Store
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


def _recorded(memory_dir: Path) -> dict[str, str] | None:
    record = memory_dir / ADAPTER_RECORD
    return json.loads(record.read_text()) if record.exists() else None


def _check_base_model(memory_dir: Path, model: str) -> None:
    if (memory_dir / "adapter").exists() and not (memory_dir / ADAPTER_RECORD).exists():
        raise TrainingRefusedError(f"{memory_dir} holds an adapter with no {ADAPTER_RECORD}")
    recorded = _recorded(memory_dir)
    if recorded is not None and recorded["model"] != model:
        raise TrainingRefusedError(f"{memory_dir} holds an adapter for {recorded['model']}")


_SHAREABLE_FIRST = tuple(AdapterProvenance)


def _record_adapter(memory_dir: Path, model: str, lessons: list[Lesson]) -> AdapterProvenance:
    """Write the adapter's record after a successful run; provenance only ever narrows.

    Continued training cannot remove what the adapter already holds, so the record keeps the
    least shareable of what it held before and what this run added.
    """
    added = (
        AdapterProvenance.PUBLIC
        if all(lesson.spark_safe for lesson in lessons)
        else AdapterProvenance.OWN_HISTORY_WITH_CONSENT
    )
    recorded = _recorded(memory_dir)
    held = AdapterProvenance(recorded["provenance"]) if recorded else AdapterProvenance.PUBLIC
    provenance = max(added, held, key=_SHAREABLE_FIRST.index)
    record = {"model": model, "provenance": provenance.value}
    (memory_dir / ADAPTER_RECORD).write_text(json.dumps(record, indent=1) + "\n")
    return provenance


def train(args: argparse.Namespace) -> dict[str, object]:
    """Export, train, forget; returns counts. Raises TrainingRefusedError, forgetting nothing."""
    store = Store.open(args.data_dir / "store.db")
    lessons = lessons_for_memory_model(store, args.project, read_consent(args.data_dir))
    if not lessons:
        raise TrainingRefusedError(f"no untrained lessons for {args.project}; mine first")
    _check_base_model(args.memory_dir, args.model)
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
    provenance = _record_adapter(args.memory_dir, args.model, lessons)
    forgotten = store.forget_trained(args.project, manifest, exported=lessons)
    return {
        "lessons_trained": len(lessons),
        "training_rows": len(rows),
        "lessons_forgotten": forgotten,
        "train_seconds": round(time.monotonic() - started, 1),
        "model": args.model,
        "provenance": provenance.value,
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
    except (
        TrainingRefusedError,
        SparkPrivacyViolationError,
        ConsentFileError,
        ForgetMismatchError,
    ) as refused:
        print(f"train_memory: {refused}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
