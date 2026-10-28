"""Score LCAP answers and write results/lesson-capacity.json (counts, ids, labels only).

Every adapter row is printed beside its floor (base model, no adapter) and its ceiling (the set's
lessons in the prompt) on the same questions. A missing answer file stops the run; it is never
scored as zero.

Usage: uv run python scripts/routea/score_answers.py --work W --tag TAG:full --out OUT
"""

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from lessons import Lesson
from questions import Asks
from scoring import score, vocabulary

SIZES = (10, 30, 100)
ROLES = {"floor": "floor", "ceiling": "ceiling", "adapter": "under test", "grouped": "under test"}
# Which (arm, size) cells a run_lcap.sh MATRIX produces; a cell outside it is not scored, and a
# cell inside it with no answer file stops the run.
MATRICES = {
    "full": [(arm, size) for arm in ROLES for size in SIZES],
    "top": [("floor", 100), ("ceiling", 100), ("adapter", 100)],
}
# Template set (training never saw the wording) and the base model's paraphrases of it.
QUESTION_SETS = {
    "template": ("questions.jsonl", ""),
    "paraphrase": ("questions-para.jsonl", "para-"),
}
SAMPLE_PER_ARM = 3  # human-readable sample, described by field, never quoted
_PEAK = re.compile(r"(\d+)\s+peak memory footprint")  # bytes, from /usr/bin/time -l


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path}: run run_lcap.sh for this tag first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _answers(answers_dir: Path, prefix: str, arm: str, size: int) -> dict[str, str]:
    """question_id -> answer for one arm at one set size."""
    if arm == "floor":
        names = ["floor-one-100"]
    elif arm == "grouped":
        names = [f"grouped-group-{g:02d}" for g in range(-(-size // 10))]
    else:
        names = [f"{arm}-one-{size}"]
    files = [answers_dir / f"{prefix}{name}.jsonl" for name in names]
    return {row["question_id"]: row["answer"] for path in files for row in _jsonl(path)}


def _cell(rows: Iterable[tuple[dict, Lesson, str]], known: frozenset[str]) -> dict[str, object]:
    asked, hits, invented, by_asks = 0, 0, 0, Counter()
    lesson_hits: Counter[str] = Counter()
    for question, lesson, answer in rows:
        verdict = score(answer, lesson, Asks(question["asks"]), known)
        asked += 1
        hits += verdict.hit
        invented += bool(verdict.invented)
        by_asks[f"{question['asks']}_hits"] += verdict.hit
        lesson_hits[lesson.lesson_id] += verdict.hit
    return {
        "questions": asked,
        "recall": round(hits / asked, 4),
        "invented_rate": round(invented / asked, 4),
        "hits_by_kind": dict(by_asks),
        "lessons_with_any_hit": sum(1 for n in lesson_hits.values() if n),
    }


def _sample(rows: list[tuple[dict, Lesson, str]], known: frozenset[str]) -> list[dict]:
    picked = rows[:: max(1, len(rows) // SAMPLE_PER_ARM)][:SAMPLE_PER_ARM]
    described = []
    for question, lesson, answer in picked:
        verdict = score(answer, lesson, Asks(question["asks"]), known)
        described.append(
            {
                "question_id": question["question_id"],
                "kind": question["asks"],
                "hit": verdict.hit,
                "names_error_class": lesson.error_class in answer,
                "fix_tokens_named": sum(token in answer for token in lesson.added),
                "fix_tokens": len(lesson.added),
                "invented_details": len(verdict.invented),
                "answer_words": len(answer.split()),
            }
        )
    return described


def _training(logs: Path) -> dict[str, dict[str, float]]:
    timing = dict(
        line.split()
        for line in (logs / "timing.txt").read_text().splitlines()
        if " " in line and not line.startswith("lcap")
    )
    budget = {
        line.split()[0]: int(line.split()[1].removeprefix("iters="))
        for line in (logs / "budget.txt").read_text().splitlines()
    }
    stats = {}
    for step, iters in budget.items():
        peaks = _PEAK.findall((logs / f"{step}.log").read_text())
        stats[step.removeprefix("train-")] = {
            "iters": iters,
            "seconds": int(timing[step]),
            "peak_mem_gb": round(max(map(int, peaks)) / 1e9, 2) if peaks else None,
        }
    return stats


def _scored_rows(
    answers_dir: Path, matrix: str, prefix: str, lessons: list[Lesson], questions: list[dict]
) -> tuple[list[dict], dict]:
    tag = answers_dir.name
    known = vocabulary(lessons)
    by_id = {lesson.lesson_id: lesson for lesson in lessons}
    rows_out, samples = [], {}
    for arm, size in MATRICES[matrix]:
        in_set = {lesson.lesson_id for lesson in lessons[:size]}
        answers = _answers(answers_dir, prefix, arm, size)
        rows = [
            (q, by_id[q["lesson_id"]], answers[q["question_id"]])
            for q in questions
            if q["lesson_id"] in in_set
        ]
        cell = _cell(rows, known)
        label = f"{tag} {arm} {size}"
        rows_out.append({"label": label, "arm": arm, "role": ROLES[arm], "lessons": size, **cell})
        if size == max(SIZES):
            samples[arm] = _sample(rows, known)
    return rows_out, samples


def score_tag(work: Path, tag: str, matrix: str, lessons: list[Lesson]) -> dict:
    """Every cell of `matrix` for one model tag, on each question set."""
    scored: dict[str, object] = {"matrix": matrix}
    for name, (filename, prefix) in QUESTION_SETS.items():
        questions = _jsonl(work / "data" / filename)
        rows, samples = _scored_rows(work / "answers" / tag, matrix, prefix, lessons, questions)
        scored[f"rows_{name}"] = rows
        if name == "template":
            scored["sample"] = samples
    scored["training"] = _training(work / "logs" / tag)
    return scored


def _row_line(question_set: str, row: dict) -> str:
    recall, invented = row["recall"], row["invented_rate"]
    label, role = row["label"], row["role"]
    return f"{question_set:10} {label:30} {role:10} recall={recall:.3f} invented={invented:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--tag", action="append", required=True, help="TAG:full or TAG:top")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--extra", type=Path, help="json object of run labels merged into the file")
    args = parser.parse_args()
    work = args.work.expanduser()
    lessons = [
        Lesson(**{**row, "added": tuple(row["added"])})
        for row in _jsonl(work / "data" / "lessons.jsonl")
    ]
    result = json.loads(args.extra.read_text()) if args.extra else {}
    result["build"] = json.loads((work / "data" / "build-counts.json").read_text())
    result["paraphrase_build"] = json.loads((work / "data" / "para-counts.json").read_text())
    tags = dict(spec.split(":") for spec in args.tag)
    result["models"] = {tag: score_tag(work, tag, matrix, lessons) for tag, matrix in tags.items()}
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    for scored in result["models"].values():
        for name in QUESTION_SETS:
            for row in scored[f"rows_{name}"]:
                print(_row_line(name, row))


if __name__ == "__main__":
    main()
