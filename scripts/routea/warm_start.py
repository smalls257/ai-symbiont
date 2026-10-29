"""Warm start: does the 1B memory model learn a new repo's lessons from fewer of them on habits?

Usage: uv run python scripts/routea/warm_start.py plan --pool P --out W
       uv run python scripts/routea/warm_start.py score --work W --out results/F.json

Exploratory, no prereg. Per repo the lessons nest (5 within 10 within 20) and both starts train on
the same rows; recall is the LCAP scorer's, and the habits start's gain is paired by repo and
bootstrapped over repos. A missing answer file raises: it is never scored as zero.
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Appended, not prepended: scripts/aidev has its own `lessons` module, and routea's must win.
sys.path.append(str(ROOT / "scripts" / "aidev"))

from lessons import Lesson  # noqa: E402
from questions import Asks, _training_pairs, held_out_questions, training_messages  # noqa: E402
from score_habits import score as habit_score  # noqa: E402
from scoring import score, vocabulary  # noqa: E402

BUDGETS = (5, 10, 20)  # lessons per repo, the coordinator's design
MIN_LESSONS = 10  # a repo needs two budgets to draw a curve
STARTS = ("plain", "habits")
ROLE = {"plain": "reference", "habits": "under_test"}
# The asks of each training pair in `questions._training_pairs`, in order: the verbatim probes.
VERBATIM_ASKS = (Asks.NOTE, Asks.FIX, Asks.FIX, Asks.ERROR, Asks.ERROR, Asks.NOTE)
VALID_ROWS = 8
RESAMPLES = 10_000
SEED = 0
# Scored hold-out and excluded repos of the T46 pool (`symbiont.eval.repo_pool`).
BLOCKED = frozenset({"python-pillow/Pillow", "iterative/dvc", "conan-io/conan", "tobymao/sqlglot"})


def distinct_by_repo(candidates: Sequence[Lesson]) -> dict[str, list[Lesson]]:
    """Each repo's distinct failures (repo, error class, fix tokens), in lesson-id order."""
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    found: dict[str, list[Lesson]] = defaultdict(list)
    for lesson in sorted(candidates, key=lambda item: item.lesson_id):
        key = (lesson.repo, lesson.error_class, lesson.added)
        if key in seen or lesson.repo in BLOCKED:
            continue
        seen.add(key)
        found[lesson.repo].append(lesson)
    return {repo: items for repo, items in found.items() if len(items) >= MIN_LESSONS}


def budgets_for(lessons: Sequence[Lesson]) -> list[int]:
    """Every budget the repo has enough lessons for."""
    return [budget for budget in BUDGETS if budget <= len(lessons)]


def probes(lessons: Sequence[Lesson]) -> list[dict]:
    """Verbatim probes (the training questions) and paraphrased ones (LCAP held-out wordings)."""
    found = []
    for lesson in lessons:
        for index, ((text, _), asks) in enumerate(
            zip(_training_pairs(lesson), VERBATIM_ASKS, strict=True)
        ):
            found.append(_probe(f"{lesson.lesson_id}-v{index}", lesson, asks, text, "verbatim"))
        for question in held_out_questions(lesson):
            probe = _probe(
                question.question_id, lesson, question.asks, question.text, "paraphrased"
            )
            found.append(probe)
    return found


def _probe(question_id: str, lesson: Lesson, asks: Asks, text: str, wording: str) -> dict:
    return {
        "question_id": question_id,
        "lesson_id": lesson.lesson_id,
        "asks": asks.value,
        "text": text,
        "wording": wording,
    }


def recall_by_wording(probes_asked: Sequence[dict], answers: dict[str, str], lessons) -> dict:
    """Recall per wording; raises KeyError when a probe has no answer."""
    by_id = {lesson.lesson_id: lesson for lesson in lessons}
    known = vocabulary(lessons)
    hits: Counter[str] = Counter()
    asked: Counter[str] = Counter()
    for probe in probes_asked:
        answer = answers[probe["question_id"]]
        verdict = score(answer, by_id[probe["lesson_id"]], Asks(probe["asks"]), known)
        asked[probe["wording"]] += 1
        hits[probe["wording"]] += verdict.hit
    return {wording: hits[wording] / asked[wording] for wording in asked}


def paired_gain(gains: Sequence[float], resamples: int = RESAMPLES, seed: int = SEED) -> dict:
    """Mean of per-repo gains and a 95% bootstrap interval over repos."""
    if not gains:
        raise ValueError("no paired repos")
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(gains) for _ in gains) / len(gains) for _ in range(resamples))
    return {
        "repos": len(gains),
        "mean_gain": round(sum(gains) / len(gains), 4),
        "ci95_low": round(means[int(0.025 * resamples)], 4),
        "ci95_high": round(means[int(0.975 * resamples) - 1], 4),
    }


def write_plan(by_repo: dict[str, list[Lesson]], work: Path) -> dict:
    """Training rows and probes per repo and budget under `work`; returns counts."""
    counts: dict[str, dict] = {}
    for repo, lessons in sorted(by_repo.items()):
        slug = repo.replace("/", "__")
        for budget in budgets_for(lessons):
            chosen = lessons[:budget]
            rows = [row for lesson in chosen for row in training_messages(lesson)]
            folder = work / "train" / slug / str(budget)
            _jsonl(folder / "train.jsonl", rows)
            _jsonl(folder / "valid.jsonl", rows[:VALID_ROWS])
            _jsonl(work / "probes" / slug / f"{budget}.jsonl", probes(chosen))
        _jsonl(work / "lessons" / f"{slug}.jsonl", [asdict(lesson) for lesson in lessons])
        counts[slug] = {"lessons": len(lessons), "budgets": budgets_for(lessons)}
    (work / "plan.json").write_text(json.dumps(counts, indent=1, sort_keys=True))
    return counts


def _jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path}: run warm_start.sh first")
    return [json.loads(line) for line in path.read_text().splitlines()]


def run_scores(work: Path, start: str, slug: str, budget: int, lessons: list[Lesson]) -> dict:
    """Recall per wording and the habits hit rate of one trained adapter."""
    asked = _read_jsonl(work / "probes" / slug / f"{budget}.jsonl")
    answers = _answers(work / "answers" / start / f"{slug}-{budget}.jsonl")
    recall = recall_by_wording(asked, answers, lessons[:budget])
    habit_questions = _read_jsonl(work / "habit_questions.jsonl")
    habit_answers = _answers(work / "answers" / start / f"{slug}-{budget}-habits.jsonl")
    return {**recall, "habits": habit_score(habit_questions, habit_answers)["hit_rate"]}


def _answers(path: Path) -> dict[str, str]:
    return {row["question_id"]: row["answer"] for row in _read_jsonl(path)}


def curve(cells: dict[tuple[str, str, int], dict]) -> list[dict]:
    """Rows of mean recall per start, budget and measure, over the repos that reached the budget."""
    rows = []
    for budget in BUDGETS:
        for start in STARTS:
            found = [c for (s, _, b), c in cells.items() if s == start and b == budget]
            if not found:
                continue
            row = {
                "arm": f"{start}_start",
                "role": ROLE[start],
                "budget": budget,
                "repos": len(found),
            }
            for measure in ("verbatim", "paraphrased", "habits"):
                row[f"{measure}_recall"] = round(sum(c[measure] for c in found) / len(found), 4)
            rows.append(row)
    return rows


def gains(cells: dict[tuple[str, str, int], dict]) -> dict:
    """Habits start minus plain start, paired by repo, per budget and measure."""
    found = {}
    for budget in BUDGETS:
        slugs = sorted({slug for (_, slug, b) in cells if b == budget})
        for measure in ("verbatim", "paraphrased", "habits"):
            paired = [
                cells[("habits", slug, budget)][measure] - cells[("plain", slug, budget)][measure]
                for slug in slugs
            ]
            if len(paired) > 1:
                found[f"{measure}_at_{budget}"] = paired_gain(paired)
    return found


def score_all(work: Path) -> dict:
    """Every cell, the curve and the paired gains."""
    plan = json.loads((work / "plan.json").read_text())
    cells = {}
    for slug, entry in plan.items():
        lessons = [
            Lesson(**{**row, "added": tuple(row["added"])})
            for row in _read_jsonl(work / "lessons" / f"{slug}.jsonl")
        ]
        for budget in entry["budgets"]:
            for start in STARTS:
                cells[(start, slug, budget)] = run_scores(work, start, slug, budget, lessons)
    return {
        "status": "exploratory, no prereg; Llama 3.2 1B MLX LoRA on the laptop",
        "rule": (
            "Per repo, nested lesson budgets train a LoRA from plain 1B and from the AIDev habits "
            "adapter on the same rows; recall is the LCAP scorer on that repo's probes."
        ),
        "repos": len(plan),
        "repos_by_budget": dict(Counter(b for entry in plan.values() for b in entry["budgets"])),
        "rows": curve(cells),
        "paired_gain_habits_minus_plain": gains(cells),
    }


def main() -> None:
    """`plan` writes rows and probes; `score` writes the results file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("plan", "score"))
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.stage == "plan":
        import build_lessons  # noqa: PLC0415  (reads the pool; only the plan stage needs it)

        unreadable: list[str] = []
        candidates, _, _ = build_lessons._candidates(args.pool, unreadable)
        counts = write_plan(distinct_by_repo(candidates), args.work)
        print(json.dumps({"repos": len(counts), "unreadable": len(unreadable), "plan": counts}))
        return
    document = score_all(args.work)
    text = json.dumps(document, indent=1, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
