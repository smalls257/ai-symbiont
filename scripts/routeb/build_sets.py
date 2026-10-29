"""Build Route B's 10, 30 and 100-lesson training sets and held-out questions for Glimmer.

Lessons come from LCAP's builder on the public OpenHands pool, which stops on any other provenance.
Paraphrased held-out questions are LCAP's, re-checked here: one whose lesson is not in the pool's
build, or that no longer names its repo and command, stops the run. Only counts are printed.

Usage: uv run python scripts/routeb/build_sets.py --pool P --paraphrases Q --work W
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "routea"))  # LCAP's bare-name modules

from build_lessons import build as build_lcap  # noqa: E402
from cards import SYSTEM, ceiling_system, training_rows  # noqa: E402
from lessons import Lesson  # noqa: E402
from paraphrase_rules import keeps_details  # noqa: E402

SIZES = (10, 30, 100)  # dispatch: lesson capacity at 10 / 30 / 100 lessons in one adapter
SEED = 0


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _lessons(lcap_dir: Path) -> list[Lesson]:
    rows = _jsonl(lcap_dir / "lessons.jsonl")
    return [Lesson(**{**row, "added": tuple(row["added"])}) for row in rows]


def checked_paraphrases(paraphrases: list[dict], questions: list[dict], lessons: list[Lesson]):
    """LCAP's paraphrases, each tied to a held-out question of this build; raises otherwise."""
    asked = {question["question_id"]: question for question in questions}
    by_id = {lesson.lesson_id: lesson for lesson in lessons}
    for row in paraphrases:
        original = asked.get(row["question_id"].removesuffix("p"))
        if original is None or original["lesson_id"] != row["lesson_id"]:
            raise ValueError(f"paraphrase {row['question_id']} has no question in this build")
        lesson = by_id[row["lesson_id"]]
        if not keeps_details(original["text"], row["text"], lesson.repo, lesson.file):
            raise ValueError(f"paraphrase {row['question_id']} drops its repo or command")
    return paraphrases


def _write_size(data: Path, size: int, lessons: list[Lesson], asked: dict[str, list[dict]]) -> int:
    name, in_set = f"one-{size}", {lesson.lesson_id for lesson in lessons[:size]}
    rows = [row for lesson in lessons[:size] for row in training_rows(lesson)]
    random.Random(SEED).shuffle(rows)
    _write_jsonl(data / "train" / name / "train.jsonl", rows)
    (data / "context").mkdir(parents=True, exist_ok=True)
    (data / "context" / f"{name}.txt").write_text(ceiling_system(lessons[:size]), encoding="utf-8")
    for folder, questions in asked.items():
        _write_jsonl(
            data / folder / f"{name}.jsonl", [q for q in questions if q["lesson_id"] in in_set]
        )
    return len(rows)


def build(pool: Path, paraphrase_file: Path, work: Path) -> dict[str, object]:
    """Write work/data in LCAP's layout (one-N sets only); return counts."""
    data = work / "data"
    lcap_counts = build_lcap(pool, work / "lcap")
    lessons = _lessons(work / "lcap")
    questions = _jsonl(work / "lcap" / "questions.jsonl")
    paraphrases = checked_paraphrases(_jsonl(paraphrase_file), questions, lessons)
    _write_jsonl(data / "lessons.jsonl", _jsonl(work / "lcap" / "lessons.jsonl"))
    _write_jsonl(data / "questions.jsonl", questions)
    _write_jsonl(data / "questions-para.jsonl", paraphrases)
    asked = {"ask": questions, "ask-para": paraphrases}
    (data / "context").mkdir(parents=True, exist_ok=True)
    (data / "context" / "memory.txt").write_text(SYSTEM, encoding="utf-8")
    rows = {f"one-{size}": _write_size(data, size, lessons, asked) for size in SIZES}
    para_counts = {
        "asked": len(questions),
        "kept": len(paraphrases),
        "lessons_covered": len({row["lesson_id"] for row in paraphrases}),
    }
    (data / "para-counts.json").write_text(json.dumps(para_counts))
    per_lesson = len(training_rows(lessons[0]))
    counts = {**lcap_counts, "training_rows": rows, "rows_per_lesson": per_lesson}
    (data / "build-counts.json").write_text(json.dumps(counts, indent=1))
    return {**counts, "paraphrases": para_counts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--paraphrases", type=Path, required=True, help="LCAP questions-para.jsonl")
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    paths = (args.pool, args.paraphrases, args.work)
    counts = build(*(path.expanduser() for path in paths))
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
