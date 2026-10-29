"""Plug a2-distract: meta-train the reader with another repo's lessons mixed into its prompt.

Usage: uv run python scripts/routea/plug_distract.py prepare --pool P --habit-split S --habit-rows H
Usage:   --scored-plan F --work W
Usage: uv run python scripts/routea/plug_distract.py score --work W --out results/F.json

Exploratory, on the a3 rerun's 10 repos (same split, `plug_a3.plan_rerun`). Training prompts hold a
repo's own lessons beside distractors and must answer from the one that applies. The test adds a
mixed prompt (own and wrong lessons shuffled) for a2-distract, a2v and a1.
"""

import argparse
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parent / "aidev"))  # appended: routea's `lessons` must win

from l2l_quick import ABSTAIN, MAX_META_ROWS, MAX_ROW_CHARS, chat, read_lessons, row_chars  # noqa: E402
from lessons import Lesson  # noqa: E402
from plug import distinct  # noqa: E402
from plug_a3 import BUDGET, plan_rerun, repo_cells  # noqa: E402
from questions import _training_pairs, lessons_prompt  # noqa: E402
from warm_start import _jsonl, _read_jsonl, answerer_provenance, paired_gain  # noqa: E402

OWN = 1  # lessons of the repo itself per training prompt
# Another repo's lessons beside it: 3 lessons per prompt as in a2v; 4 overflow the window.
DISTRACTORS = 2
SEED = 0
ARMS = ("a1", "a2v", "a2d")
ROLE = {"a1": "reference", "a2v": "reference", "a2d": "under_test"}


def distract_rows(by_repo: dict[str, list[Lesson]], seed: int = SEED) -> list[dict]:
    """Own lessons mixed with another repo's in the prompt, plus abstain rows without them."""
    rng = random.Random(seed)
    repos = sorted(by_repo)
    rows = []
    for repo in repos:
        lessons = by_repo[repo]
        others = [r for r in repos if r != repo]
        for start in range(0, len(lessons), OWN):
            own = lessons[start : start + OWN]
            wrong = by_repo[rng.choice(others)][:DISTRACTORS] if others else []
            mixed = own + wrong
            rng.shuffle(mixed)
            context = lessons_prompt(mixed)
            for lesson in own:
                rows.extend(chat(context, q, a) for q, a in _training_pairs(lesson))
                question = rng.choice(_training_pairs(lesson))[0]
                rows.append(chat(lessons_prompt(wrong), question, ABSTAIN))
    rng.shuffle(rows)
    return rows[:MAX_META_ROWS]


def mixed_context(own: Sequence[Lesson], wrong: Sequence[Lesson], seed: int = SEED) -> str:
    """The test's mixed prompt: own and wrong lessons in one fixed shuffled order."""
    lessons = list(own) + list(wrong)
    random.Random(seed).shuffle(lessons)
    return lessons_prompt(lessons)


def prepare(args: argparse.Namespace) -> dict:
    """a2-distract meta rows from the rerun's meta repos, and a mixed context per test repo."""
    import build_lessons  # noqa: PLC0415  (reads the pool)

    candidates, _, _ = build_lessons._candidates(args.pool, [])
    split_json = json.loads(args.habit_split.read_text())
    habit_repos = [r for r, s in split_json.items() if s == "train"]
    plan = json.loads((args.work / "plan.json").read_text())
    scored = set(json.loads(args.scored_plan.read_text())["test_repos"])
    split = plan_rerun(distinct(candidates), scored, habit_repos)
    if sorted(split.test) != sorted(plan["test_repos"]):
        raise ValueError("the rerun's test repos changed since its plan")
    built = distract_rows(split.meta)
    kept = [row for row in built if row_chars(row) <= MAX_ROW_CHARS]
    rows = kept + _read_jsonl(args.habit_rows)
    random.Random(SEED).shuffle(rows)
    _jsonl(args.work / "meta-distract" / "train.jsonl", rows)
    _jsonl(args.work / "meta-distract" / "valid.jsonl", rows[:8])
    for repo in plan["test_repos"]:
        folder = args.work / "repos" / repo.replace("/", "__")
        own = read_lessons(folder / "lessons.jsonl")[:BUDGET]
        wrong = read_lessons(folder / "wrong-lessons.jsonl")
        (folder / "mixed.txt").write_text(mixed_context(own, wrong))
    return {
        "rows": len(rows),
        "distract_rows": len(kept),
        "dropped_too_long": len(built) - len(kept),
    }


def mixed_cell(folder: Path, arm: str) -> dict:
    """Recall and confabulation of one arm with own and wrong lessons mixed in its prompt."""
    from plug import abstains, confabulates  # noqa: PLC0415
    from warm_start import recall_by_wording  # noqa: PLC0415

    own = read_lessons(folder / "lessons.jsonl")[:BUDGET]
    wrong = read_lessons(folder / "wrong-lessons.jsonl")
    asked = _read_jsonl(folder / "probes.jsonl")
    rows = _read_jsonl(folder / "answers" / arm / "mixed_lessons.jsonl")
    answers = {row["question_id"]: row["answer"] for row in rows}
    texts = [answers[p["question_id"]] for p in asked if p["wording"] == "paraphrased"]
    return {
        "mixed_lessons": recall_by_wording(asked, answers, own)["paraphrased"],
        "mixed_confabulation": sum(confabulates(t, own, wrong) for t in texts) / len(texts),
        "mixed_false_abstention": sum(abstains(t) for t in texts) / len(texts),
    }


def score(work: Path) -> dict:
    """Pooled rows for a1, a2v and a2-distract over the 10 repos, with per-repo rows."""
    plan = json.loads((work / "plan.json").read_text())
    habit_questions = _read_jsonl(work / "habit_questions.jsonl")
    cells = {}
    for repo in plan["test_repos"]:
        folder = work / "repos" / repo.replace("/", "__")
        for arm in ARMS:
            cells[(arm, repo)] = {
                **repo_cells(folder, arm, habit_questions),
                **mixed_cell(folder, arm),
            }
    rows = []
    for arm in ARMS:
        found = [cell for (a, _), cell in sorted(cells.items()) if a == arm]
        row = {"arm": arm, "role": ROLE[arm], "repos": len(found)}
        for measure in found[0]:
            interval = paired_gain([cell[measure] for cell in found])
            row[measure] = interval["mean_gain"]
            row[f"{measure}_ci95"] = [interval["ci95_low"], interval["ci95_high"]]
        rows.append(row)
    return {
        "status": "exploratory, no prereg; Llama 3.2 1B MLX on the laptop",
        "rows": rows,
        "per_repo_rows": [
            {"arm": arm, "repo": repo, **{k: round(v, 4) for k, v in cell.items()}}
            for (arm, repo), cell in sorted(cells.items())
        ],
        **answerer_provenance(work),
    }


def main() -> None:
    """`prepare` before the driver trains and answers; `score` after."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("prepare", "score"))
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--habit-split", type=Path)
    parser.add_argument("--habit-rows", type=Path)
    parser.add_argument("--scored-plan", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.stage == "prepare":
        print(json.dumps(prepare(args), indent=1))
        return
    text = json.dumps(score(args.work), indent=1, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
