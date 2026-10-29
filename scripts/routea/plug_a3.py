"""Plug a3 rerun: consolidation arms on repos that neither a2 variant nor the scored run touches.

Usage: uv run python scripts/routea/plug_a3.py plan --pool P --habit-split S --habit-rows H --work W
Usage: uv run python scripts/routea/plug_a3.py score --work W --out results/F.json

Exploratory. Test repos hold 8 or 9 lessons: 5 trained, 3 held back as new lessons. The a2 variant
is meta-trained without them and without the 13 scored Plug repos (`plug.check_unseen` raises on a
shared repo or lesson id). Every column is a mean over repos with a bootstrap interval by repo.
"""

import argparse
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parent / "aidev"))  # appended: routea's `lessons` must win

from l2l_quick import MIX, read_lessons  # noqa: E402
from lessons import Lesson  # noqa: E402
from plug import (  # noqa: E402
    FEASIBILITY_REPOS,
    MIN_META_LESSONS,
    Split,
    abstains,
    check_unseen,
    confabulates,
    distinct,
    meta_train_rows,
)
from questions import lessons_prompt, training_messages  # noqa: E402
from score_habits import score as keyword_habits  # noqa: E402
from warm_start import (  # noqa: E402
    _jsonl,
    _read_jsonl,
    answerer_provenance,
    paired_gain,
    probes,
    recall_by_wording,
)

BUDGET = 5
NEW_LESSONS = 3
TEST_SIZES = range(BUDGET + NEW_LESSONS, 10)  # 8 or 9: a 10-lesson repo belongs to the scored run
ARMS = ("per_repo", "a1", "a2v", "a3", "a3_more", "a3_replay", "a3_more_replay")
# a3-more-replay must also keep habits near a2v: ranked habits at least a2v's minus this,
# fixed before its run (owner GO, 2026-10-29).
HABITS_NEAR = 0.10
ROLE = {"per_repo": "reference", "a1": "reference", "a2v": "reference"}
SEED = 0


def plan_rerun(by_repo: dict[str, list[Lesson]], scored: set[str], habit_repos: list[str]) -> Split:
    """Test repos (8 or 9 lessons), meta repos (the rest with 2 or more), name-sorted pairing."""
    blocked = scored | FEASIBILITY_REPOS
    test = {r: items for r, items in sorted(by_repo.items()) if len(items) in TEST_SIZES}
    meta = {
        r: items
        for r, items in sorted(by_repo.items())
        if r not in test and r not in blocked and len(items) >= MIN_META_LESSONS
    }
    names = sorted(test)
    split = Split(test, meta, {r: names[(i + 1) % len(names)] for i, r in enumerate(names)})
    check_unseen(split, habit_repos)
    if scored & set(meta):
        raise ValueError("a scored Plug repo reached the a2 variant's meta-train")
    return split


def arm_rows(own: list[dict], reading: list[dict], habits: list[dict], arm: str) -> list[dict]:
    """Training rows of one consolidation arm, shuffled with a fixed seed."""
    rng = random.Random(SEED)
    rows = own + rng.sample(reading, MIX * len(own))
    if arm == "a3_replay":
        rows += rng.sample(habits, len(own))
    rng.shuffle(rows)
    return rows


def write_rerun(split: Split, rows: list[dict], habits: list[dict], work: Path) -> dict:
    """Meta rows, per-repo rows, contexts and probes for every test repo."""
    _jsonl(work / "meta" / "train.jsonl", rows)
    _jsonl(work / "meta" / "valid.jsonl", rows[:8])
    reading = [r for r in rows if "What you remember:" in r["messages"][0]["content"]]
    for repo, lessons in split.test.items():
        slug = repo.replace("/", "__")
        trained, new = lessons[:BUDGET], lessons[BUDGET : BUDGET + NEW_LESSONS]
        wrong = split.test[split.control_of[repo]][:BUDGET]
        folder = work / "repos" / slug
        own = [row for lesson in trained for row in training_messages(lesson)]
        _jsonl(folder / "per_repo" / "train.jsonl", own)
        _jsonl(folder / "per_repo" / "valid.jsonl", own[:8])
        for arm in ("a3", "a3_replay"):
            mixed = arm_rows(own, reading, habits, arm)
            _jsonl(folder / arm / "train.jsonl", mixed)
            _jsonl(folder / arm / "valid.jsonl", mixed[:8])
        (folder / "right.txt").write_text(lessons_prompt(trained))
        (folder / "wrong.txt").write_text(lessons_prompt(wrong))
        (folder / "new.txt").write_text(lessons_prompt(new))
        _jsonl(folder / "probes.jsonl", probes(trained))
        _jsonl(folder / "probes-new.jsonl", probes(new))
        _jsonl(folder / "lessons.jsonl", [asdict(item) for item in lessons])
        _jsonl(folder / "wrong-lessons.jsonl", [asdict(item) for item in wrong])
    plan = {
        "test_repos": {r: len(v) for r, v in split.test.items()},
        "control_of": split.control_of,
        "meta_train_repos": len(split.meta),
        "meta_train_rows": len(rows),
    }
    (work / "plan.json").write_text(json.dumps(plan, indent=1, sort_keys=True))
    return plan


def wrong_lesson_rates(answers: dict[str, str], asked: Sequence[dict], own, wrong) -> dict:
    """Confabulation and abstention under the wrong repo's lessons."""
    texts = [answers[p["question_id"]] for p in asked if p["wording"] == "paraphrased"]
    return {
        "confabulation": sum(confabulates(t, own, wrong) for t in texts) / len(texts),
        "abstention": sum(abstains(t) for t in texts) / len(texts),
    }


def repo_cells(folder: Path, arm: str, habit_questions: list[dict]) -> dict:
    """The five measures of one arm on one repo."""
    lessons = read_lessons(folder / "lessons.jsonl")
    trained, new = lessons[:BUDGET], lessons[BUDGET : BUDGET + NEW_LESSONS]
    wrong = read_lessons(folder / "wrong-lessons.jsonl")
    asked = _read_jsonl(folder / "probes.jsonl")
    out = folder / "answers" / arm

    def recall(name: str, probes_asked: Sequence[dict], pool) -> float:
        return recall_by_wording(probes_asked, _answers(out / f"{name}.jsonl"), pool)["paraphrased"]

    cell = {
        "no_lessons": recall("no_lessons", asked, trained),
        "lessons_in_prompt": recall("lessons_in_prompt", asked, trained),
        "new_lessons": recall("new_lessons", _read_jsonl(folder / "probes-new.jsonl"), new),
        "wrong_lessons": recall("wrong_lessons", asked, trained),
    }
    wrong_answers = _answers(out / "wrong_lessons.jsonl")
    cell |= {
        f"wrong_{k}": v for k, v in wrong_lesson_rates(wrong_answers, asked, trained, wrong).items()
    }
    keyword = keyword_habits(habit_questions, _answers(out / "habits.jsonl"))["hit_rate"]
    ranked = _read_jsonl(out / "ranked.jsonl")
    cell["habits_keyword"] = keyword
    cell["habits_ranked"] = sum(row["hit"] for row in ranked) / len(ranked)
    return cell


def _answers(path: Path) -> dict[str, str]:
    return {row["question_id"]: row["answer"] for row in _read_jsonl(path)}


def pooled(cells: dict[tuple[str, str], dict]) -> list[dict]:
    """Per arm: each measure's mean over repos with its bootstrap interval."""
    rows = []
    for arm in ARMS:
        found = [cell for (a, _), cell in sorted(cells.items()) if a == arm]
        if not found:
            continue
        row = {"arm": arm, "role": ROLE.get(arm, "under_test"), "repos": len(found)}
        for measure in found[0]:
            interval = paired_gain([cell[measure] for cell in found])
            row[measure] = interval["mean_gain"]
            row[f"{measure}_ci95"] = [interval["ci95_low"], interval["ci95_high"]]
        rows.append(row)
    return rows


def score_rerun(work: Path) -> dict:
    """Pooled rows, per-repo rows and the plan counts."""
    plan = json.loads((work / "plan.json").read_text())
    habit_questions = _read_jsonl(work / "habit_questions.jsonl")
    cells = {}
    for repo in plan["test_repos"]:
        folder = work / "repos" / repo.replace("/", "__")
        for arm in ARMS:
            cells[(arm, repo)] = repo_cells(folder, arm, habit_questions)
    per_repo = [
        {"arm": arm, "repo": repo, **{k: round(v, 4) for k, v in cell.items()}}
        for (arm, repo), cell in sorted(cells.items())
    ]
    return {
        "status": "exploratory, no prereg; Llama 3.2 1B MLX on the laptop",
        "rule": (
            "Go if recall without lessons reaches the per-repo adapter and new-lesson recall "
            "reaches a2; kill if new-lesson recall falls below a1."
        ),
        "plan": plan,
        "rows": pooled(cells),
        "verdicts": verdicts(pooled(cells)),
        "paired": paired(cells),
        **answerer_provenance(work),
        "per_repo_rows": per_repo,
    }


# Each consolidation arm against the reference its go rule names, paired by repo.
PAIRED = (("no_lessons", "per_repo"), ("new_lessons", "a2v"), ("habits_ranked", "a2v"))


def paired(cells: dict[tuple[str, str], dict]) -> dict:
    """Arm minus reference per repo, with a bootstrap interval, for each go-rule measure."""
    repos = sorted({repo for _, repo in cells})
    found = {}
    for arm in (
        a for a in ("a3", "a3_more", "a3_replay", "a3_more_replay") if (a, repos[0]) in cells
    ):
        for measure, reference in PAIRED:
            gains = [cells[(arm, r)][measure] - cells[(reference, r)][measure] for r in repos]
            found[f"{arm}_minus_{reference}_{measure}"] = paired_gain(gains)
    return found


def passes(by: dict[str, dict], arm: str) -> bool:
    """The go conditions; a3-more-replay must also keep habits near a2v's."""
    go = (
        by[arm]["no_lessons"] >= by["per_repo"]["no_lessons"]
        and by[arm]["new_lessons"] >= by["a2v"]["new_lessons"]
    )
    if arm == "a3_more_replay":
        go = go and by[arm]["habits_ranked"] >= by["a2v"]["habits_ranked"] - HABITS_NEAR
    return go


def verdicts(rows: list[dict]) -> dict[str, str]:
    """go, hold or kill per consolidation arm present, by the owner's rule on the pooled means."""
    by = {row["arm"]: row for row in rows}
    found = {}
    for arm in (a for a in ("a3", "a3_more", "a3_replay", "a3_more_replay") if a in by):
        if by[arm]["new_lessons"] < by["a1"]["new_lessons"]:
            found[arm] = "kill"
        else:
            found[arm] = "go" if passes(by, arm) else "hold"
    return found


def main() -> None:
    """`plan` writes the split and rows; `score` writes the results file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("plan", "score"))
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--habit-split", type=Path)
    parser.add_argument("--habit-rows", type=Path)
    parser.add_argument("--scored-plan", type=Path, help="the scored Plug plan.json")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.stage == "score":
        text = json.dumps(score_rerun(args.work), indent=1, sort_keys=True)
        if args.out:
            args.out.write_text(text + "\n")
        print(text)
        return
    import build_lessons  # noqa: PLC0415  (reads the pool)

    candidates, _, _ = build_lessons._candidates(args.pool, [])
    habit_split = json.loads(args.habit_split.read_text())
    habit_repos = [r for r, s in habit_split.items() if s == "train"]
    scored = set(json.loads(args.scored_plan.read_text())["test_repos"])
    split = plan_rerun(distinct(candidates), scored, habit_repos)
    habits = _read_jsonl(args.habit_rows)
    rows, _ = meta_train_rows(split, habits)
    print(json.dumps(write_rerun(split, rows, habits, args.work), indent=1))


if __name__ == "__main__":
    main()
