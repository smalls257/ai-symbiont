"""Score recall of the sqlglot lessons, LCAP-style: exact key details, never a judged match.

A note hit needs the lesson's place (`Class.member`) and its file verbatim; the check command is
counted on its own. A file or dotted place the answer names that no lesson holds counts as
invented. Floor and adapter arms are scored on the same questions; a missing answer stops the run.

Usage: python score_sqlglot_recall.py --work SQLGLOT_WORK --answers DIR [--out OUT.json]
"""

import argparse
import json
import re
from pathlib import Path

ARMS = ("floor", "adapter")  # floor: plain Glimmer; adapter: the sqlglot LoRA at scale 1
_FILE = re.compile(r"\b[\w/]+\.py\b")
_PLACE = re.compile(r"\b[A-Z]\w*\.[A-Za-z_]\w*\b")
_TICKS = re.compile(r"`")


def _flat(text: str) -> str:
    return " ".join(_TICKS.sub(" ", text).split())


def details_in(text: str) -> set[str]:
    """File paths and dotted places (`Parser.TYPE_TOKENS`) a text names."""
    flat = _flat(text)
    return {*_FILE.findall(flat), *_PLACE.findall(flat)}


def vocabulary(lessons: list[dict]) -> frozenset[str]:
    """Every file and place any lesson names: an answer may say these without inventing."""
    fields = ("happened", "resolved", "check", "file", "place")
    return frozenset(d for lesson in lessons for f in fields for d in details_in(lesson[f]))


def verdict(answer: str, lesson: dict, known: frozenset[str]) -> dict[str, bool]:
    """Which key details of `lesson` the answer carries, and whether it invents any."""
    flat = _flat(answer)
    place, file = _flat(lesson["place"]), lesson["file"]
    return {
        "place": place in flat,
        "file": file in flat,
        "check": _flat(lesson["check"]) in flat,
        "note": place in flat and file in flat,
        "invented": bool(details_in(answer) - known),
    }


def score_arm(answers: dict[str, str], questions: list[dict], lessons: dict[str, dict]):
    """Rates over every question; raises KeyError naming a question with no answer."""
    known = vocabulary(list(lessons.values()))
    rows = [verdict(answers[q["question_id"]], lessons[q["lesson_id"]], known) for q in questions]
    rates = {key: round(sum(r[key] for r in rows) / len(rows), 4) for key in rows[0]}
    return {"questions": len(rows), **{f"{key}_rate": rate for key, rate in rates.items()}}


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    lessons = {row["lesson_id"]: row for row in _jsonl(args.work / "lessons.jsonl")}
    questions = _jsonl(args.work / "questions.jsonl")
    result = {}
    for arm in ARMS:
        answers = {r["question_id"]: r["answer"] for r in _jsonl(args.answers / f"{arm}.jsonl")}
        result[arm] = score_arm(answers, questions, lessons)
    print(json.dumps(result, indent=1))
    if args.out:
        args.out.write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
