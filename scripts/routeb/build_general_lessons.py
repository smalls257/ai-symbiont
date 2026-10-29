"""Build the general sqlglot lessons, the prompt card and the Route B training set.

Evidence excludes every task in the committed split; every text is scanned against every
evaluation task's gold patch and a hit stops the build. Text goes under --out (local only);
--manifest gets ids, kinds, counts and the scan result.
Usage: uv run python scripts/routeb/build_general_lessons.py --src S --split F --clone C
         --out W --manifest M
"""

import argparse
import dataclasses
import hashlib
import json
import random
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from general_card import card
from general_evidence import EvaluationLeakError, Evidence, load_evidence
from general_habit_lessons import habit_lessons
from general_implementation import implementation_lessons
from general_knowledge import features, knowledge_lessons
from general_leakage import conventions, leaking_keys, pattern_close, scan
from general_lesson import GeneralLesson
from general_rows import action_rows, lesson_rows, recall_question
from sqlglot_rows import TrainingRow

SEED = 0  # build_sets.py's shuffle seed
SET = "sqlglot-general"


def lessons_from(evidence: Evidence) -> list[GeneralLesson]:
    """Habit, repo-knowledge and implementation lessons; raises if one cites an evaluation task."""
    tasks = list(evidence.tasks.values())
    gold = {task.task: task.gold_files for task in tasks}
    built = habit_lessons(list(evidence.runs), gold) + knowledge_lessons(tasks)
    built += implementation_lessons(features(tasks))
    cited = sorted({t for lesson in built for t in lesson.source_tasks} & evidence.evaluation)
    if cited:
        raise EvaluationLeakError(f"lessons cite evaluation tasks: {cited}")
    return built


def rows_from(
    evidence: Evidence, lessons: Sequence[GeneralLesson], common: set[str]
) -> tuple[list[TrainingRow], int]:
    """Q&A rows plus corrected-action rows, shuffled, and how many action rows were dropped.

    An action row quotes another task's issue title; one that names a code word of an evaluation
    fix is dropped and counted. Lesson rows are never dropped: a hit there stops the build.
    """
    gold = {task.task: task.gold_files for task in evidence.tasks.values()}
    actions = action_rows(evidence.runs, evidence.tasks, gold)
    keyed = {str(i): "\n".join(m["content"] for m in row.messages) for i, row in enumerate(actions)}
    dropped = leaking_keys(keyed, evidence.evaluation_patches, common)
    rows = [row for lesson in lessons for row in lesson_rows(lesson)]
    rows += [row for i, row in enumerate(actions) if str(i) not in dropped]
    random.Random(SEED).shuffle(rows)
    return rows, len(dropped)


def texts(lessons, card_text: str, rows, questions) -> dict[str, str]:
    """Every text the build writes, by a key that names where it came from."""
    found = {f"lesson:{x.lesson_id}": f"{x.situation}\n{x.card()}" for x in lessons}
    found |= {
        f"row{i}:{r.lesson_id}:{r.kind}": "\n".join(m["content"] for m in r.messages)
        for i, r in enumerate(rows)
    }
    found |= {q["question_id"]: q["text"] for q in questions}
    return found | {"card": card_text}


def _jsonl(path: Path, items: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")


def write_outputs(out: Path, built: "Built", evaluation: frozenset[str]) -> None:
    """Lessons, card, training set, recall questions and the pilot's lesson file, all local."""
    lessons, card_text, rows, questions = built.lessons, built.card, built.rows, built.questions
    _jsonl(out / "lessons.jsonl", [dataclasses.asdict(lesson) for lesson in lessons])
    (out / "card.txt").write_text(card_text + "\n", encoding="utf-8")
    _jsonl(out / "train" / SET / "train.jsonl", [{"messages": row.messages} for row in rows])
    _jsonl(
        out / "train" / SET / "index.jsonl",
        [{"lesson_id": r.lesson_id, "kind": r.kind} for r in rows],
    )
    _jsonl(out / "questions.jsonl", questions)
    pilot = out / "pilot"
    pilot.mkdir(parents=True, exist_ok=True)
    (pilot / "general-card.json").write_text(
        json.dumps({t: card_text for t in sorted(evaluation)}, indent=1)
    )
    _jsonl(pilot / "eval-tasks.jsonl", [{"instance_id": task} for task in sorted(evaluation)])


@dataclasses.dataclass(frozen=True)
class Built:
    """Everything the build writes."""

    lessons: list[GeneralLesson]
    card: str
    rows: list[TrainingRow]
    questions: list[dict[str, str]]


def lesson_entry(lesson: GeneralLesson) -> dict:
    """A lesson's manifest entry: ids, kind and counts, no text."""
    return {
        "lesson_id": lesson.lesson_id,
        "kind": str(lesson.kind),
        "support": lesson.support,
        "source_task_count": len(lesson.source_tasks),
        "source_tasks": list(lesson.source_tasks),
    }


def build(args: argparse.Namespace) -> dict:
    """Run the whole build; return the manifest."""
    evidence = load_evidence(args.src, args.split, args.clone)
    lessons = lessons_from(evidence)
    card_text = card({lesson.lesson_id: lesson for lesson in lessons})
    common = conventions(task.gold_patch for task in evidence.tasks.values())
    rows, dropped = rows_from(evidence, lessons, common)
    questions = [recall_question(lesson) for lesson in lessons]
    leakage = scan(texts(lessons, card_text, rows, questions), evidence.evaluation_patches, common)
    write_outputs(args.out, Built(lessons, card_text, rows, questions), evidence.evaluation)
    return {
        "label": "exploratory: general sqlglot lessons from non-evaluation history",
        "source_tasks": len(evidence.tasks),
        "source_runs": len(evidence.runs),
        "source_tasks_with_runs": len({run.task for run in evidence.runs}),
        "places_unresolved": sum(not t.places_resolved for t in evidence.tasks.values()),
        "lessons_by_kind": dict(Counter(str(lesson.kind) for lesson in lessons)),
        "rows": len(rows),
        "rows_by_kind": dict(Counter(row.kind for row in rows)),
        "action_rows_dropped_for_eval_names": dropped,
        "card_words": len(card_text.split()),
        "card_sha": hashlib.sha256(card_text.encode()).hexdigest()[:16],
        "leakage": leakage,
        "pattern_close": pattern_close(lessons, evidence.evaluation_places),
        "lessons": [lesson_entry(lesson) for lesson in lessons],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--src", "--split", "--clone", "--out", "--manifest"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    manifest = build(args)
    args.manifest.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    keys = (
        "lessons_by_kind",
        "rows",
        "rows_by_kind",
        "action_rows_dropped_for_eval_names",
        "card_words",
        "leakage",
    )
    print(json.dumps({key: manifest[key] for key in keys}, indent=1))


if __name__ == "__main__":
    main()
