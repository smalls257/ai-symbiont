"""Build the sqlglot Route B training set from Glimmer's own public sqlglot runs.

`sqlglot-own` holds lessons resolved by Glimmer itself (solved runs, capability pairs, repo habits);
`sqlglot-all` adds never-solved tasks resolved by the public upstream fix. A row carrying any
evaluation task's gold line stops the build. Text stays under --out (local); --manifest gets ids,
sources, runs and evaluation-task links only.

Usage: uv run python scripts/routeb/build_sqlglot_set.py --src S --rows R --clone C
         --curated J --out W --manifest results/routeb-sqlglot-lessons.json
"""

import argparse
import dataclasses
import json
import random
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from sqlglot_evidence import gold_patches, load_evidence
from sqlglot_leakage import gold_lines, refuse_leaks
from sqlglot_lessons import Lesson
from sqlglot_rows import TrainingRow, held_out_question, training_rows
from sqlglot_select import EVAL_TASKS, TIER1, Selection, own_history, select

SEED = 0  # build_sets.py's shuffle seed


def _write_jsonl(path: Path, rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _rows(lessons: Sequence[Lesson]) -> list[TrainingRow]:
    rows = [row for lesson in lessons for row in training_rows(lesson)]
    random.Random(SEED).shuffle(rows)
    return rows


def _refuse_held_out_prompts(rows: Sequence[TrainingRow], questions: Sequence[dict]) -> None:
    prompts = {message["content"] for row in rows for message in row.messages}
    reused = [q["question_id"] for q in questions if q["text"] in prompts]
    if reused:
        raise ValueError(f"held-out questions used as training prompts: {reused[:5]}")


def _write_set(out: Path, name: str, rows: Sequence[TrainingRow]) -> None:
    _write_jsonl(out / "train" / name / "train.jsonl", [{"messages": r.messages} for r in rows])
    index = [{"lesson_id": row.lesson_id, "kind": row.kind} for row in rows]
    _write_jsonl(out / "train" / name / "index.jsonl", index)


def _texts(rows: Sequence[TrainingRow], questions: Sequence[dict]) -> dict[str, str]:
    texts = {
        f"row{i}:{row.lesson_id}:{row.kind}": "\n".join(m["content"] for m in row.messages)
        for i, row in enumerate(rows)
    }
    return texts | {q["question_id"]: q["text"] for q in questions}


def _eval_view(lessons: Sequence[Lesson], rows: Sequence[TrainingRow]) -> dict[str, dict]:
    per_lesson = Counter(row.lesson_id for row in rows)
    view: dict[str, dict] = {}
    for task in EVAL_TASKS:
        linked = [
            (lesson, link) for lesson in lessons for target, link in lesson.links if target == task
        ]
        view[task] = {
            "tier": 1 if task in TIER1 else 2,
            "lessons": {lesson.lesson_id: link.value for lesson, link in linked},
            "rows": sum(per_lesson[lesson.lesson_id] for lesson, _ in linked),
        }
    return view


def _lesson_entry(lesson: Lesson) -> dict:
    return {
        "lesson_id": lesson.lesson_id,
        "source": lesson.source.value,
        "task": lesson.task,
        "runs": list(lesson.runs),
        "links": [{"eval_task": task, "link": link.value} for task, link in lesson.links],
        "stall_run": lesson.stall.run_id if lesson.stall else None,
    }


def counts(selection: Selection, sets: dict[str, list[Lesson]], rows: dict) -> dict:
    """Lessons per source and set, rows per set and kind, drops by reason, per eval task."""
    return {
        "lessons_by_source": {
            name: dict(Counter(lesson.source.value for lesson in found))
            for name, found in sets.items()
        },
        "rows": {name: len(found) for name, found in rows.items()},
        "rows_by_kind": {
            name: dict(Counter(row.kind for row in found)) for name, found in rows.items()
        },
        "drops": {reason.value: count for reason, count in selection.drops.items()},
        "eval_tasks": _eval_view(sets["sqlglot-all"], rows["sqlglot-all"]),
    }


def build(args: argparse.Namespace) -> dict:
    """Write lessons, both training sets, held-out questions and counts; return the manifest."""
    evidence = load_evidence(args.src, args.rows, args.clone)
    curated_text = {
        task: parts
        for task, parts in json.loads(args.curated.read_text(encoding="utf-8")).items()
        if not task.startswith("_")
    }
    selection = select(evidence, curated_text)
    sets = {"sqlglot-all": selection.lessons, "sqlglot-own": own_history(selection.lessons)}
    rows = {name: _rows(found) for name, found in sets.items()}
    questions = [held_out_question(lesson) for lesson in selection.lessons]
    gold = {task: gold_lines(patch) for task, patch in gold_patches(args.rows, EVAL_TASKS).items()}
    checked = refuse_leaks(_texts(rows["sqlglot-all"], questions), gold)
    _refuse_held_out_prompts(rows["sqlglot-all"], questions)
    for name, found in rows.items():
        _write_set(args.out, name, found)
    _write_jsonl(args.out / "lessons.jsonl", [dataclasses.asdict(x) for x in selection.lessons])
    _write_jsonl(args.out / "questions.jsonl", questions)
    found = counts(selection, sets, rows)
    found |= {
        "tasks_attempted": len(evidence),
        "runs_read": sum(len(e.runs) for e in evidence.values()),
    }
    found["leakage"] = {"texts_checked": checked, "eval_tasks": len(gold), "hits": 0}
    (args.out / "counts.json").write_text(json.dumps(found, indent=1), encoding="utf-8")
    return {
        "label": "exploratory: sqlglot Route B lessons from Glimmer's public calibration runs",
        **found,
        "lessons": [_lesson_entry(lesson) for lesson in selection.lessons],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--src", "--rows", "--clone", "--curated", "--out", "--manifest"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    manifest = build(args)
    args.manifest.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    summary = {key: manifest[key] for key in ("lessons_by_source", "rows", "drops", "leakage")}
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
