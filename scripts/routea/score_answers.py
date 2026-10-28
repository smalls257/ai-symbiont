"""Score LCAP answers and write results/lesson-capacity.json (counts, ids, labels only).

Every adapter row is printed beside its floor (base model, no adapter) and its ceiling (the
lessons in the prompt), on the same questions. A missing answer file stops the run; it is never
scored as zero.
Usage: uv run python scripts/routea/score_answers.py --work ... --tag llama-1b --out ...
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
SAMPLE_PER_ARM = 3  # human-readable sample, described by field, never quoted
_PEAK = re.compile(r"(\d+)\s+peak memory footprint")  # bytes, from /usr/bin/time -l


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path}: run run_lcap.sh for this tag first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _answers(answers_dir: Path, arm: str, size: int) -> dict[str, str]:
    """question_id -> answer for one arm at one set size."""
    if arm == "floor":
        files = [answers_dir / "floor-one-100.jsonl"]
    elif arm == "grouped":
        files = [answers_dir / f"grouped-group-{g:02d}.jsonl" for g in range(-(-size // 10))]
    else:
        files = [answers_dir / f"{arm}-one-{size}.jsonl"]
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


def score_tag(work: Path, tag: str, lessons: list[Lesson], questions: list[dict]) -> dict:
    """Every arm x size for one model tag."""
    known = vocabulary(lessons)
    by_id = {lesson.lesson_id: lesson for lesson in lessons}
    rows_out, samples = [], {}
    for arm, role in ROLES.items():
        for size in SIZES:
            in_set = {lesson.lesson_id for lesson in lessons[:size]}
            answers = _answers(work / "answers" / tag, arm, size)
            rows = [
                (q, by_id[q["lesson_id"]], answers[q["question_id"]])
                for q in questions
                if q["lesson_id"] in in_set
            ]
            rows_out.append(
                {
                    "label": f"{arm} {size}",
                    "arm": arm,
                    "role": role,
                    "lessons": size,
                    **_cell(rows, known),
                }
            )
            if size == max(SIZES):
                samples[arm] = _sample(rows, known)
    return {"rows": rows_out, "sample": samples, "training": _training(work / "logs" / tag)}


def _row_line(tag: str, row: dict) -> str:
    recall, invented = row["recall"], row["invented_rate"]
    label, role = row["label"], row["role"]
    return f"{tag:12} {label:12} {role:10} recall={recall:.3f} invented={invented:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--tag", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--extra", type=Path, help="json object of run labels merged into the file")
    args = parser.parse_args()
    work = args.work.expanduser()
    lessons = [
        Lesson(**{**row, "added": tuple(row["added"])})
        for row in _jsonl(work / "data" / "lessons.jsonl")
    ]
    questions = _jsonl(work / "data" / "questions.jsonl")
    result = json.loads(args.extra.read_text()) if args.extra else {}
    result["build"] = json.loads((work / "data" / "build-counts.json").read_text())
    result["models"] = {tag: score_tag(work, tag, lessons, questions) for tag in args.tag}
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    for tag, scored in result["models"].items():
        for row in scored["rows"]:
            print(_row_line(tag, row))


if __name__ == "__main__":
    main()
