"""Learn-to-learn feasibility on one unseen repo: lessons in prompt, stacked adapter, meta-train.

Usage: uv run python scripts/routea/l2l_quick.py contexts --work W --repo SLUG --control SLUG
Usage: uv run python scripts/routea/l2l_quick.py meta --pool P --work W --habits H --out D
Usage: uv run python scripts/routea/l2l_quick.py {score,consolidation,score-a3} --work W [--out F]

Exploratory, no prereg. Every arm reports new-lesson recall, habits kept, and recall with another
repo's lessons in the prompt: an arm whose recall survives wrong lessons is memorizing, not
reading. A missing answer file raises.
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

from lessons import Lesson  # noqa: E402
from questions import _training_pairs, lessons_prompt  # noqa: E402
from score_habits import score as habit_score  # noqa: E402
from warm_start import (  # noqa: E402
    BLOCKED,
    _jsonl,
    _read_jsonl,
    answerer_provenance,
    ranked_rate,
    recall_by_wording,
)

BUDGETS = (5, 10)
WINDOW = 3  # lessons per meta-train prompt; 5 overflow the 512-token training window [measured]
# Rows longer than this are dropped and counted, never truncated by the trainer; at 1400 one
# row reached 535 tokens [measured], at 1300 none passed 512 (`check_tokens.py`).
MAX_ROW_CHARS = 1300
ABSTAIN = "No lesson I hold covers that."
MAX_META_ROWS = 1600  # bounds the meta-train run to minutes on the laptop
NEW_LESSONS = 3  # the repo's last lessons, never trained: does a3 still read its prompt?
# The reference rows of the feasibility run; every other arm is under test.
REFERENCE_ARMS = frozenset({"warm_plain", "warm_habits"})
MIX = 2  # prompt-reading rows from train repos per repo row in a3, so the skill is rehearsed
SEED = 0


def read_lessons(path: Path) -> list[Lesson]:
    """Lessons written by `warm_start.py plan`."""
    return [Lesson(**{**row, "added": tuple(row["added"])}) for row in _read_jsonl(path)]


def chat(system: str, question: str, answer: str) -> dict:
    """One mlx-lm chat row."""
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    }


def windows(lessons: Sequence[Lesson]) -> list[list[Lesson]]:
    """Consecutive groups of WINDOW lessons; a short tail joins the group before it."""
    groups = [list(lessons[i : i + WINDOW]) for i in range(0, len(lessons), WINDOW)]
    if len(groups) > 1 and len(groups[-1]) < 2:
        groups[-2].extend(groups.pop())
    return groups


def meta_rows(by_repo: dict[str, list[Lesson]], seed: int = SEED) -> list[dict]:
    """Read-the-context rows: answers from lessons in the prompt, abstain when they are absent."""
    rng = random.Random(seed)
    repos = sorted(by_repo)
    rows = []
    for repo in repos:
        for group in windows(by_repo[repo]):
            context = lessons_prompt(group)
            for lesson in group:
                rows.extend(chat(context, q, a) for q, a in _training_pairs(lesson))
                other = by_repo[rng.choice([r for r in repos if r != repo] or [repo])]
                question = rng.choice(_training_pairs(lesson))[0]
                rows.append(chat(lessons_prompt(other[:WINDOW]), question, ABSTAIN))
    rng.shuffle(rows)
    return rows[:MAX_META_ROWS]


def row_chars(row: dict) -> int:
    """Characters of a chat row's messages."""
    return sum(len(message["content"]) for message in row["messages"])


def arm_scores(work: Path, arm: str, probes: Sequence[dict], lessons: Sequence[Lesson]) -> dict:
    """New-lesson recall, wrong-lesson recall and habits kept for one arm at one budget."""
    answers = work / "answers" / arm
    right = recall_by_wording(probes, _answers(answers / "right.jsonl"), lessons)
    wrong = recall_by_wording(probes, _answers(answers / "wrong.jsonl"), lessons)
    habits = habit_score(
        _read_jsonl(work / "habit_questions.jsonl"), _answers(answers / "habits.jsonl")
    )
    ranked = answers / "ranked.jsonl"
    return {
        "habits_kept_ranked": round(ranked_rate(ranked), 4),
        "new_lesson_recall": round(right["paraphrased"], 4),
        "new_lesson_recall_verbatim": round(right["verbatim"], 4),
        "wrong_lesson_recall": round(wrong["paraphrased"], 4),
        "habits_kept": habits["hit_rate"],
    }


def _answers(path: Path) -> dict[str, str]:
    return {row["question_id"]: row["answer"] for row in _read_jsonl(path)}


def write_contexts(warm: Path, work: Path, repo: str, control: str) -> None:
    """Lesson contexts for each budget: the repo's own and the control repo's."""
    own = read_lessons(warm / "lessons" / f"{repo}.jsonl")
    other = read_lessons(warm / "lessons" / f"{control}.jsonl")
    for budget in BUDGETS:
        (work / f"right-{budget}.txt").write_text(lessons_prompt(own[:budget]))
        (work / f"wrong-{budget}.txt").write_text(lessons_prompt(other[:budget]))


def write_meta(pool: Path, work: Path, habits: Path, out: Path) -> dict:
    """Meta-train rows from every pool repo but the test and control repos, plus habit rows."""
    import build_lessons  # noqa: PLC0415  (reads the pool; only this stage needs it)

    held = json.loads((work / "held.json").read_text())
    candidates, _, _ = build_lessons._candidates(pool, [])
    by_repo: dict[str, list[Lesson]] = {}
    for lesson in sorted(candidates, key=lambda item: item.lesson_id):
        slug = lesson.repo.replace("/", "__")
        if lesson.repo in BLOCKED or slug in held:
            continue
        by_repo.setdefault(lesson.repo, []).append(lesson)
    built = meta_rows(by_repo)
    kept = [row for row in built if row_chars(row) <= MAX_ROW_CHARS]
    rows = kept + _read_jsonl(habits)
    random.Random(SEED).shuffle(rows)
    _jsonl(out / "train.jsonl", rows)
    _jsonl(out / "valid.jsonl", rows[:8])
    return {"meta_rows": len(kept), "dropped_too_long": len(built) - len(kept), "rows": len(rows)}


def write_consolidation(warm: Path, work: Path) -> dict:
    """a3 rows per budget (repo rows plus MIX reading rows each), new-lesson context and probes."""
    from warm_start import probes  # noqa: PLC0415

    held = json.loads((work / "held.json").read_text())
    lessons = read_lessons(warm / "lessons" / f"{held[0]}.jsonl")
    if len(lessons) < max(BUDGETS) + NEW_LESSONS:
        raise ValueError(
            f"{held[0]} holds {len(lessons)} lessons, needs {max(BUDGETS) + NEW_LESSONS}"
        )
    new = lessons[-NEW_LESSONS:]
    (work / "new.txt").write_text(lessons_prompt(new))
    _jsonl(work / "probes-new.jsonl", probes(new))
    reading = _read_jsonl(work / "meta" / "train.jsonl")
    reading = [row for row in reading if "What you remember:" in row["messages"][0]["content"]]
    counts = {}
    for budget in BUDGETS:
        own = _read_jsonl(warm / "train" / held[0] / str(budget) / "train.jsonl")
        mixed = random.Random(SEED + budget).sample(reading, MIX * len(own))
        rows = own + mixed
        random.Random(SEED).shuffle(rows)
        _jsonl(work / "a3" / str(budget) / "train.jsonl", rows)
        _jsonl(work / "a3" / str(budget) / "valid.jsonl", rows[:8])
        counts[budget] = {"repo_rows": len(own), "reading_rows": len(mixed)}
    return counts


def score_consolidation(warm: Path, work: Path) -> dict:
    """Per arm and budget: recall without lessons, with them, of new lessons, and wrong lessons."""
    held = json.loads((work / "held.json").read_text())
    lessons = read_lessons(warm / "lessons" / f"{held[0]}.jsonl")
    new_probes = _read_jsonl(work / "probes-new.jsonl")
    rows = []
    for arm_dir in sorted((work / "answers-a3").iterdir()):
        arm, budget = arm_dir.name.rsplit("-", 1)
        probes = _read_jsonl(warm / "probes" / held[0] / f"{budget}.jsonl")
        trained = lessons[: int(budget)]
        row = {
            "arm": arm,
            "budget": int(budget),
            "role": "under_test" if arm == "a3" else "reference",
        }
        for name, asked, pool in (
            ("no_lessons", probes, trained),
            ("lessons_in_prompt", probes, trained),
            ("wrong_lessons", probes, trained),
            ("new_lessons", new_probes, lessons[-NEW_LESSONS:]),
        ):
            answers = _answers(arm_dir / f"{name}.jsonl")
            row[f"{name}_recall"] = round(recall_by_wording(asked, answers, pool)["paraphrased"], 4)
        habits = _answers(arm_dir / "habits.jsonl")
        row["habits_kept_keyword"] = habit_score(
            _read_jsonl(work / "habit_questions.jsonl"), habits
        )["hit_rate"]
        row["habits_kept_ranked"] = round(ranked_rate(arm_dir / "ranked.jsonl"), 4)
        rows.append(row)
    return {
        "status": "exploratory feasibility, one repo, no prereg; a3 consolidation vs a2 and a1",
        "rule": (
            "Go if recall without lessons reaches the per-repo adapter and new-lesson recall "
            "reaches a2; kill if new-lesson recall falls below a1."
        ),
        "repo": held[0],
        "rows": rows,
        "verdict": consolidation_verdict(rows, per_repo_recall(warm, work, held[0], lessons)),
        **answerer_provenance(work),
    }


def per_repo_recall(
    warm: Path, work: Path, repo: str, lessons: Sequence[Lesson]
) -> dict[int, float]:
    """The plain per-repo adapter's recall with no lessons in the prompt, per budget."""
    found = {}
    for budget in BUDGETS:
        probes = _read_jsonl(warm / "probes" / repo / f"{budget}.jsonl")
        answers = _answers(work / "answers" / f"warm_plain-{budget}" / "right.jsonl")
        found[budget] = recall_by_wording(probes, answers, lessons[:budget])["paraphrased"]
    return found


def consolidation_verdict(rows: Sequence[dict], per_repo: dict[int, float]) -> dict:
    """go, hold or kill per budget and overall, by the owner's rule for a3."""
    by = {(row["arm"], row["budget"]): row for row in rows}
    labels = {}
    for budget in BUDGETS:
        a3, a2, a1 = (by[(arm, budget)] for arm in ("a3", "a2", "a1"))
        new = a3["new_lessons_recall"]
        if new < a1["new_lessons_recall"]:
            labels[budget] = "kill"
        elif a3["no_lessons_recall"] >= per_repo[budget] and new >= a2["new_lessons_recall"]:
            labels[budget] = "go"
        else:
            labels[budget] = "hold"
    values = set(labels.values())
    overall = "kill" if "kill" in values else "go" if values == {"go"} else "hold"
    return {
        "label": overall,
        "by_budget": {str(b): v for b, v in labels.items()},
        "per_repo_adapter_no_lessons": {str(b): round(v, 4) for b, v in per_repo.items()},
    }


def score_all(warm: Path, work: Path) -> dict:
    """Every arm at every budget, from the answer files under `work/answers/<arm>-<budget>`."""
    held = json.loads((work / "held.json").read_text())
    lessons = read_lessons(warm / "lessons" / f"{held[0]}.jsonl")
    rows = []
    for arm_dir in sorted((work / "answers").iterdir()):
        arm, budget = arm_dir.name.rsplit("-", 1)
        probes = _read_jsonl(warm / "probes" / held[0] / f"{budget}.jsonl")
        cell = arm_scores(work, arm_dir.name, probes, lessons[: int(budget)])
        role = "reference" if arm in REFERENCE_ARMS else "under_test"
        rows.append({"arm": arm, "budget": int(budget), "role": role, **cell})
    return {
        "status": "exploratory feasibility, one repo, no prereg; Llama 3.2 1B MLX on the laptop",
        "repo": held[0].replace("__", "/"),
        "control_repo": held[1].replace("__", "/"),
        "rows": rows,
        **answerer_provenance(work),
    }


def main() -> None:
    """Dispatch the stage."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("contexts", "meta", "score", "consolidation", "score-a3"))
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--warm", type=Path, default=Path.home() / "symbiont-runs/aidev/warm")
    parser.add_argument("--repo")
    parser.add_argument("--control")
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--habits", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.stage == "contexts":
        (args.work / "held.json").write_text(json.dumps([args.repo, args.control]))
        write_contexts(args.warm, args.work, args.repo, args.control)
    elif args.stage == "consolidation":
        print(json.dumps(write_consolidation(args.warm, args.work)))
    elif args.stage == "score-a3":
        text = json.dumps(score_consolidation(args.warm, args.work), indent=1, sort_keys=True)
        if args.out:
            args.out.write_text(text + "\n")
        print(text)
    elif args.stage == "meta":
        print(json.dumps(write_meta(args.pool, args.work, args.habits, args.out)))
    else:
        text = json.dumps(score_all(args.warm, args.work), indent=1, sort_keys=True)
        if args.out:
            args.out.write_text(text + "\n")
        print(text)


if __name__ == "__main__":
    main()
