"""Score answers to held-out habit questions: did the answer name the check its lesson teaches?

Usage: python scripts/aidev/score_habits.py --questions Q.jsonl --answers ARM=A.jsonl ...
       [--record results/aidev-lessons.json --answerer-record W/answerer.sha256]

Deterministic like the LCAP scorer: a hit needs the kind's key term; naming only another kind's
term is off-kind, so "add tests" to everything cannot score on every kind. The base model's row
is printed beside the adapter's; a question with no answer raises.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

KEY_TERMS = {
    "tests_missing": re.compile(r"\btests?\b|\btesting\b"),
    "error_handling": re.compile(r"\b(errors?|exceptions?|except|raise[sd]?|failures?)\b"),
    "wrong_module": re.compile(r"\b(modules?|where similar code|already lives|belongs?)\b"),
    "api_misuse": re.compile(r"\b(signatures?|deprecat\w*|documentation|docs)\b"),
    "naming_convention": re.compile(r"\b(names?|naming|conventions?|style)\b"),
}


ROLE = {
    "base": "floor"
}  # the base model without the adapter is the floor; every adapter is under test


def verdict(answer: str, kind: str) -> str:
    """`hit`, `off_kind` (names only other kinds' checks) or `miss`."""
    text = answer.lower()
    if KEY_TERMS[kind].search(text):
        return "hit"
    others = (rule for name, rule in KEY_TERMS.items() if name != kind)
    return "off_kind" if any(rule.search(text) for rule in others) else "miss"


def score(questions: list[dict], answers: dict[str, str]) -> dict:
    """Hits, off-kind and misses overall and per kind; raises on a question with no answer."""
    missing = [q["question_id"] for q in questions if q["question_id"] not in answers]
    if missing:
        raise KeyError(f"{len(missing)} questions have no answer, first {missing[0]}")
    overall: Counter[str] = Counter()
    by_kind: dict[str, Counter[str]] = {}
    for question in questions:
        result = verdict(answers[question["question_id"]], question["kind"])
        overall[result] += 1
        by_kind.setdefault(question["kind"], Counter())[result] += 1
    return {
        "questions": len(questions),
        "hit_rate": round(overall["hit"] / len(questions), 4) if questions else None,
        "overall": dict(overall),
        "by_kind": {kind: dict(c) for kind, c in sorted(by_kind.items())},
    }


def main() -> None:
    """Print one score per arm."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--answers", nargs="+", required=True, help="ARM=answers.jsonl")
    parser.add_argument("--record", type=Path, help="results file to add the scores to")
    parser.add_argument("--answerer-record", type=Path, help="answerer.sha256 the driver wrote")
    args = parser.parse_args()
    if args.record and not args.answerer_record:
        parser.error("--record needs --answerer-record: a result must name the script behind it")
    questions = [json.loads(line) for line in args.questions.read_text().splitlines()]
    scores = {}
    for spec in args.answers:
        arm, path = spec.split("=", 1)
        rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
        scores[arm] = score(questions, {r["question_id"]: r["answer"] for r in rows})
    print(json.dumps(scores, indent=1, sort_keys=True))
    if args.record:
        document = json.loads(args.record.read_text())
        document["habit_recall"] = {
            "status": "exploratory, Llama 3.2 1B MLX LoRA, laptop, no prereg",
            "rows": [
                {"arm": arm, "role": ROLE.get(arm, "under_test"), **s} for arm, s in scores.items()
            ],
            "answer_script": "scripts/routea/answer_questions.py",
            "answer_script_sha256": args.answerer_record.read_text().strip(),
        }
        args.record.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
