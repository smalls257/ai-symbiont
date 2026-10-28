"""Build LCAP lessons, training sets and held-out questions from the public OpenHands pool.

Violation prevented: **Silent Fallback**. Lessons come only from the public nebius OpenHands
trajectories (CC-BY-4.0, spark_safe); a record with any other provenance stops the run rather
than being skipped. Every dropped pair is counted by reason. Only counts are printed: lesson
text stays in the work directory outside the repo.

    uv run python scripts/routea/build_lessons.py \
        --pool ~/symbiont-runs/t47/data/nebius-openhands/pool --out ~/symbiont-runs/lcap/data
"""

import argparse
import json
import random
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

from lessons import Lesson, lessons_in_session, select_lessons
from questions import held_out_questions, lessons_prompt, training_messages

from symbiont.readers.errors import ReadError
from symbiont.readers.openhands import PROVENANCE, read
from symbiont.records.schema import Record

SIZES = (10, 30, 100)  # dispatch: 10 / 30 / 100 lessons in one adapter
GROUP_SIZE = 10  # dispatch: grouped variant, one adapter per 10 lessons
VALID_ROWS = 8  # mlx-lm needs a valid split; it only reports loss, so a sample of train is enough
SEED = 0


def _sessions(pool: Path, unreadable: list[str]) -> Iterator[list[Record]]:
    for path in sorted(pool.glob("*.jsonl")):
        try:
            sessions = _sessions_in(path)
        except ReadError as exc:
            # One malformed row drops its whole file, by name, rather than half a file.
            print(f"skipping {path.name}: {exc}")
            unreadable.append(path.name)
            continue
        yield from sessions


def _sessions_in(path: Path) -> list[list[Record]]:
    by_session: dict[str, list[Record]] = defaultdict(list)
    for record in read(path, path.stem):
        if record.provenance != PROVENANCE:
            raise ValueError(f"{path.name}: record not from the public OpenHands dataset")
        by_session[record.session_id].append(record)
    return list(by_session.values())


def _candidates(pool: Path, unreadable: list[str]) -> tuple[list[Lesson], Counter[str], int]:
    drops: Counter[str] = Counter()
    found: list[Lesson] = []
    sessions = 0
    for session in _sessions(pool, unreadable):
        sessions += 1
        found += lessons_in_session(session, drops)
    return found, drops, sessions


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _write_condition(out: Path, name: str, lessons: list[Lesson]) -> int:
    """Training rows, the held-out questions it is asked, and the ceiling arm's context."""
    rows = [row for lesson in lessons for row in training_messages(lesson)]
    random.Random(SEED).shuffle(rows)
    _write_jsonl(out / "train" / name / "train.jsonl", rows)
    _write_jsonl(out / "train" / name / "valid.jsonl", rows[:VALID_ROWS])
    asked = [asdict(q) for lesson in lessons for q in held_out_questions(lesson)]
    _write_jsonl(out / "ask" / f"{name}.jsonl", asked)
    (out / "context").mkdir(exist_ok=True)
    (out / "context" / f"{name}.txt").write_text(lessons_prompt(lessons), encoding="utf-8")
    return len(rows)


def _conditions(lessons: list[Lesson]) -> dict[str, list[Lesson]]:
    sets = {f"one-{size}": lessons[:size] for size in SIZES}
    for start in range(0, max(SIZES), GROUP_SIZE):
        sets[f"group-{start // GROUP_SIZE:02d}"] = lessons[start : start + GROUP_SIZE]
    return sets


def build(pool: Path, out: Path) -> dict[str, object]:
    """Write lessons.jsonl, questions.jsonl and train/<condition>/; return counts only."""
    unreadable: list[str] = []
    candidates, drops, sessions = _candidates(pool, unreadable)
    lessons = select_lessons(candidates, max(SIZES))
    _write_jsonl(out / "lessons.jsonl", [asdict(lesson) for lesson in lessons])
    questions = [asdict(q) for lesson in lessons for q in held_out_questions(lesson)]
    _write_jsonl(out / "questions.jsonl", questions)
    rows = {
        name: _write_condition(out, name, group) for name, group in _conditions(lessons).items()
    }
    return {
        "files_unreadable": len(unreadable),
        "sessions_read": sessions,
        "candidate_lessons": len(candidates),
        "drops": dict(drops),
        "lessons": len(lessons),
        "repos": len({lesson.repo for lesson in lessons}),
        "error_classes": dict(Counter(lesson.error_class for lesson in lessons)),
        "programs": dict(Counter(lesson.program for lesson in lessons)),
        "held_out_questions": len(questions),
        "training_rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    counts = build(args.pool.expanduser(), args.out.expanduser())
    (args.out.expanduser() / "build-counts.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
