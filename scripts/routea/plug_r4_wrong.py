"""Plug round 4: which items make every form's cross-validated wrong pick, and why (counts only).

Usage: uv run python scripts/routea/plug_r4_wrong.py --work R3 --out F

For each form of `plug_r4_combine`, the wrong picks under repo-fold cross-validation are sorted by
how the chosen lesson relates to the lesson the situation was built from: the same failed command
and error (the situation fits both, so the "wrong" label is doubtful), the same repository only,
or neither. Validation only; no label is changed here.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge_cli import seed_mean_scores  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4_combine import candidates, cv_choices, forms  # noqa: E402


def lessons_by_id(items) -> dict:
    """Every lesson shown in the items, by id."""
    return {lesson.lesson_id: lesson for item in items for lesson in item.prompt_lessons}


def category(source, chosen) -> str:
    """How the chosen lesson relates to the situation's own lesson."""
    if (chosen.failed, chosen.error) == (source.failed, source.error):
        return "same failed command and error line"
    if chosen.failed == source.failed:
        return "same failed command, other error line"
    if chosen.error == source.error:
        return "same error line, other command"
    return "same repository only" if chosen.repo == source.repo else "other repository"


def wrong_picks(items, choices, lessons: dict) -> list[dict]:
    """Each answered item whose chosen lesson is not the applicable one, with its category."""
    by_id = {item.item_id: item for item in items}
    found = []
    for choice in choices:
        item = by_id[choice.item_id]
        right = item.applies.lesson_id if item.applies else None
        if choice.lesson_id is None or choice.lesson_id == right:
            continue
        source = lessons[choice.item_id.rsplit("-", 1)[0]]
        found.append(
            {
                "item_id": choice.item_id,
                "kind": "pick item" if right else "silence item",
                "category": category(source, lessons[choice.lesson_id]),
            }
        )
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    items, repo_of = load_items(args.work, "scored")
    scores = seed_mean_scores([args.work / "scores" / f"scored-judge-s{s}.jsonl" for s in range(3)])
    cands = candidates(items, scores)
    lessons = lessons_by_id(items) | {i.applies.lesson_id: i.applies for i in items if i.applies}
    per_form = {}
    for form in forms(items, cands):
        found = wrong_picks(items, cv_choices(items, repo_of, cands, form), lessons)
        per_form[form] = {
            "wrong_picks": len(found),
            "by_kind_and_category": dict(Counter(f"{w['kind']}: {w['category']}" for w in found)),
            "item_ids": sorted(w["item_id"] for w in found),
        }
    shared = set.intersection(*(set(f["item_ids"]) for f in per_form.values()))
    document = {
        "status": "exploratory, validation only, no label changed",
        "wrong_in_every_form": len(shared),
        "forms": per_form,
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(
        json.dumps(
            {form: {k: v for k, v in f.items() if k != "item_ids"} for form, f in per_form.items()},
            indent=1,
        )
    )
    print("wrong in every form:", len(shared))


if __name__ == "__main__":
    main()
