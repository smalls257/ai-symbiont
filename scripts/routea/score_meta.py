"""Score METALORA answers: recall and invented-detail rate per start, lessons taught and steps.

The meta start prints beside the blank and joint-trained starts (references), the floor and the
ceiling on the same held-out questions. Invented details are judged against the repo's own
lessons; a missing answer file stops the run, never scores zero. Repos are reported by index.
Usage: uv run python scripts/routea/score_meta.py --work <dir> --split test --out results/X.json
"""

import argparse
import json
import re
from collections.abc import Iterator
from pathlib import Path

from lessons import Lesson
from meta_recipe import full_budget
from questions import Asks
from scoring import score, vocabulary

ROLES = {
    "floor": "floor",
    "ceiling": "ceiling",
    "blank": "reference",
    "joint": "reference",
    "meta": "under test",
}
QUESTION_SETS = ("template", "paraphrase")
_CELL = re.compile(r"^(template|paraphrase)-(\d+)(?:-(\d+))?\.jsonl$")


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _cells_on_disk(arm_dir: Path) -> set[tuple[int, int | None]]:
    found = set()
    for path in arm_dir.glob("*/*.jsonl"):
        match = _CELL.match(path.name)
        if match:
            found.add((int(match.group(2)), int(match.group(3)) if match.group(3) else None))
    return found


def _tally(
    answers: dict[str, str], questions: list[dict], lessons: dict[str, Lesson], known
) -> tuple[int, int, int]:
    """(questions, hits, answers naming an invented detail) for one repo cell."""
    asked = hits = invented = 0
    for question in questions:
        verdict = score(
            answers[question["question_id"]],
            lessons[question["lesson_id"]],
            Asks(question["asks"]),
            known,
        )
        asked, hits, invented = asked + 1, hits + verdict.hit, invented + bool(verdict.invented)
    return asked, hits, invented


class Scorer:
    """One split's lessons and questions, scored cell by cell across its repos."""

    def __init__(self, work: Path, split: str) -> None:
        data = work / "data"
        self.answers = work / "answers" / split
        self.repos = json.loads((data / "domains.json").read_text())[split]
        rows = _jsonl(data / "lessons.jsonl")
        self.lessons = {r["lesson_id"]: Lesson(**{**r, "added": tuple(r["added"])}) for r in rows}
        self.questions = {
            "template": _jsonl(data / "questions.jsonl"),
            "paraphrase": _jsonl(data / "questions-para.jsonl"),
        }

    def row(self, arm: str, cell: tuple[int, int | None], question_set: str) -> dict:
        size, iters = cell
        name = f"{question_set}-{size}" + ("" if iters is None else f"-{iters}") + ".jsonl"
        per_repo, totals = [], [0, 0, 0]
        for repo in sorted(self.repos):
            taught = set(self.repos[repo][:size])
            asked = [q for q in self.questions[question_set] if q["lesson_id"] in taught]
            answers = {
                r["question_id"]: r["answer"]
                for r in _jsonl(self.answers / arm / repo.replace("/", "__") / name)
            }
            known = vocabulary(self.lessons[i] for i in self.repos[repo])
            counts = _tally(answers, asked, self.lessons, known)
            per_repo.append(round(counts[1] / counts[0], 4) if counts[0] else None)
            totals = [a + b for a, b in zip(totals, counts, strict=True)]
        return {
            "label": f"{arm} {size} lessons "
            + ("reference" if iters is None else f"{iters} iters"),
            "arm": arm,
            "role": ROLES.get(arm, "under test"),  # a val-grid Reptile config
            "lessons": size,
            "iters": iters,
            "questions": totals[0],
            "recall": round(totals[1] / totals[0], 4),
            "invented_rate": round(totals[2] / totals[0], 4),
            "recall_by_repo_index": per_repo,
        }

    def rows(self) -> Iterator[dict]:
        for arm_dir in sorted(p for p in self.answers.iterdir() if p.is_dir()):
            for cell in sorted(_cells_on_disk(arm_dir), key=lambda cell: (cell[0], cell[1] or 0)):
                for question_set in QUESTION_SETS:
                    yield {
                        "question_set": question_set,
                        **self.row(arm_dir.name, cell, question_set),
                    }


def reaches(rows: list[dict], arm: str, question_set: str) -> list[dict]:
    """Per lessons taught: the fewest iterations at which `arm` matches the blank start's recall
    at LCAP's full budget, and the fewest lessons at full budget matching blank at 10 lessons."""
    table = {
        (r["arm"], r["lessons"], r["iters"]): r["recall"]
        for r in rows
        if r["question_set"] == question_set
    }
    found = []
    for size in sorted({r["lessons"] for r in rows}):
        target = table.get(("blank", size, full_budget(size)))
        steps = sorted(i for (a, s, i) in table if a == arm and s == size and i is not None)
        hit = next(
            (i for i in steps if target is not None and table[(arm, size, i)] >= target), None
        )
        found.append(
            {"lessons": size, "blank_full_budget_recall": target, "fewest_iters_to_match": hit}
        )
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--split", choices=["val", "test"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--extra", type=Path, help="json object of run labels merged into the file")
    args = parser.parse_args()
    rows = list(Scorer(args.work.expanduser(), args.split).rows())
    result = json.loads(args.extra.read_text()) if args.extra else {}
    result["build"] = json.loads(
        (args.work.expanduser() / "data" / "build-counts.json").read_text()
    )
    result["rows"] = rows
    arms = sorted({r["arm"] for r in rows if r["iters"] is not None and r["arm"] != "blank"})
    result["reaches_blank"] = {
        f"{arm} {qs}": reaches(rows, arm, qs) for arm in arms for qs in QUESTION_SETS
    }
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    for row in rows:
        print(_row_line(row))


def _row_line(row: dict) -> str:
    recall, invented = row["recall"], row["invented_rate"]
    head = f"{row['question_set']:10} {row['label']:34} {row['role']:10}"
    return f"{head} recall={recall:.3f} invented={invented:.3f}"


if __name__ == "__main__":
    main()
