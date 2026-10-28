"""Build METALORA domains (one public repo each), training rows and held-out questions.

Violation prevented: **Silent Fallback**. Lessons come from the public nebius OpenHands pool
through the LCAP lesson builder (a non-public record stops the run); the repo split is checked
for hold-out leaks before anything is written (`meta_domains.check_held_out` raises). Only counts
are printed: lesson text stays in the work directory outside the repo.

A later held-out domain (the Freedoom lessons from the Act 1 learning agent) joins the test split
with `--extra-test NAME=lessons.jsonl`, a file of LCAP `Lesson` rows; it is held-out only, never
meta-trained.

    uv run python scripts/routea/build_meta_domains.py \
        --pool ~/symbiont-runs/t47/data/nebius-openhands/pool --out ~/symbiont-runs/metalora/data
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from build_lessons import _candidates
from lessons import Lesson
from meta_domains import Split, check_held_out, distinct_lessons, split_domains
from meta_recipe import SIZES, taught
from questions import held_out_questions, lessons_prompt, training_messages


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _extra_lessons(spec: str) -> tuple[str, list[Lesson]]:
    name, _, path = spec.partition("=")
    rows = [json.loads(line) for line in Path(path).expanduser().read_text().splitlines()]
    return name, [Lesson(**{**row, "added": tuple(row["added"])}) for row in rows]


def _with_extras(split: Split, lessons: list[Lesson], extras: list[str]) -> list[Lesson]:
    for spec in extras:
        name, extra = _extra_lessons(spec)
        split.test[name] = [lesson.lesson_id for lesson in extra]
        lessons += extra
    check_held_out(split)
    return lessons


def _ids(*parts: dict[str, list[str]]) -> list[str]:
    return [i for part in parts for ids in part.values() for i in ids]


def _write(out: Path, split: Split, lessons: list[Lesson]) -> dict[str, object]:
    by_id = {lesson.lesson_id: lesson for lesson in lessons}
    used = [by_id[i] for i in _ids(split.train, split.val, split.test)]
    held = [by_id[i] for i in _ids(split.val, split.test)]
    (out / "domains.json").write_text(json.dumps(asdict(split), indent=1))
    _write_jsonl(out / "lessons.jsonl", [asdict(lesson) for lesson in used])
    rows = [{"lesson_id": one.lesson_id, **row} for one in used for row in training_messages(one)]
    _write_jsonl(out / "rows.jsonl", rows)
    questions = [asdict(q) for lesson in held for q in held_out_questions(lesson)]
    _write_jsonl(out / "questions.jsonl", questions)
    (out / "contexts.json").write_text(json.dumps(_ceiling_contexts(split, by_id), indent=1))
    return {**_counts(split), "training_rows": len(rows), "held_out_questions": len(questions)}


def _ceiling_contexts(split: Split, by_id: dict[str, Lesson]) -> dict[str, dict[int, str]]:
    """The ceiling arm's prompt per held-out repo and size: the taught lessons, one per line."""
    held = {**split.val, **split.test}
    return {
        repo: {size: lessons_prompt([by_id[i] for i in taught(ids, size)]) for size in SIZES}
        for repo, ids in held.items()
    }


def _counts(split: Split) -> dict[str, object]:
    parts = asdict(split)
    return {
        "domains": {name: len(part) for name, part in parts.items()},
        "lessons": {name: sum(map(len, part.values())) for name, part in parts.items()},
        "test_lessons_per_repo": sorted(len(ids) for ids in split.test.values()),
        "val_lessons_per_repo": sorted(len(ids) for ids in split.val.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--extra-test", action="append", default=[], help="NAME=lessons.jsonl")
    args = parser.parse_args()
    out = args.out.expanduser()
    unreadable: list[str] = []
    candidates, _, sessions = _candidates(args.pool.expanduser(), unreadable)
    lessons = distinct_lessons(candidates)
    split = split_domains(lessons)
    lessons = _with_extras(split, lessons, args.extra_test)
    counts = {
        "sessions_read": sessions,
        "files_unreadable": len(unreadable),
        **_write(out, split, lessons),
    }
    (out / "build-counts.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
