"""Plug round 4, the nightly arm for the scored repositories: one adapter per repository, leak-free.

Usage: uv run python scripts/routea/plug_r4_scored_nightly.py STAGE ...  (prep, invent, rows)
Usage: prep: --primary --pool D... --dates T... --out; invent: --out --run-cap-usd
Usage: rows: --primary --work --spark --cont --pair-scores --habits --out

An adapter may only know what its repository learned BEFORE its earliest scored recurrence, so
training uses tasks created before that cutoff and nothing after it.
"""

import argparse
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import Lesson  # noqa: E402
from plug_r4_cont import (  # noqa: E402
    NightFailure,
    Stored,
    add_habits,
    candidate_pairs,
    labeled_rows,
    near_misses,
    repo_rows,
)
from plug_r4_eval import accepted, slug  # noqa: E402
from plug_r4_primary import Case, Failure, TaskEvents, case_item, load_events, merged_store  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

PAIRS_PER_REPO = (
    20  # lower than validation's 60 so labeling fits the night; validation repos averaged 9
)
INVENT_COUNT = 12
SEED = 0


def cutoffs(items, repo_of: dict, dates: dict) -> dict[str, tuple]:
    """Repo -> (date, task) of its earliest scored recurrence, where the adapter stops knowing."""
    found: dict[str, tuple] = {}
    for item in items:
        if item.applies is None:
            continue
        task = item.item_id.split(":")[1]
        key = (dates[task], task)
        repo = repo_of[item.item_id]
        found[repo] = min(found.get(repo, key), key)
    return found


def before(events: list[TaskEvents], cutoff: tuple) -> list[TaskEvents]:
    """Tasks created strictly before the cutoff (date, then task id)."""
    return [t for t in events if (t.date, t.task) < cutoff]


def known_lessons(events: list[TaskEvents]) -> list[Lesson]:
    """The repository's stored lessons from these tasks, identical ones merged."""
    return list(merged_store(x for t in events for x in t.lessons))


def stored_of(events: list[TaskEvents]) -> list[Stored]:
    """Lessons with their task, for the pair builder."""
    return [Stored(t.task, x) for t in events for x in merged_store(t.lessons)]


def night_failures(events: list[TaskEvents]) -> list[NightFailure]:
    """Distinct failures of these tasks."""
    found = {}
    for t in events:
        for f in t.failures:
            found[(t.task, f.exact())] = NightFailure(t.task, 0, f.command, f.error, f.file)
    return list(found.values())


def task_number(task: str) -> int:
    return int(task.rsplit("-", 1)[1])


def repo_picks(repo: str, store: list[Lesson], pool: list[Lesson]) -> list:
    """One pick item per stored lesson (its own situation, the store plus distractors)."""
    return [
        case_item(Case(repo, Failure("", x.failed, x.error, x.file), tuple(store), (x,)), pool)
        for x in store
    ]


def run_prep(args: argparse.Namespace) -> dict:
    """Per scored repository: its pre-cutoff lessons and the capped pairs to label."""
    items, repo_of, dates = load_primary(args)
    cut = cutoffs(items, repo_of, dates)
    by_repo = load_events(args.pool, set(cut), dates)
    lessons, pairs = [], []
    for repo, events in sorted(by_repo.items()):
        early = before(events, cut[repo])
        store = known_lessons(early)
        lessons += [asdict(x) for x in store]
        found = candidate_pairs(repo, night_failures(early), stored_of(early), set())
        random.Random(f"{SEED}:{repo}").shuffle(found)
        pairs += found[:PAIRS_PER_REPO]
    args.out.mkdir(parents=True, exist_ok=True)
    _jsonl(args.out / "lessons.jsonl", lessons)
    _jsonl(args.out / "pairs.jsonl", pairs)
    (args.out / "cutoffs.json").write_text(json.dumps({r: list(c) for r, c in cut.items()}))
    return {"repos": len(cut), "lessons": len(lessons), "pairs": len(pairs)}


def load_primary(args: argparse.Namespace):
    """The primary items, their repos and the merged task dates."""
    from plug_situation import item_from  # noqa: PLC0415

    records = _read_jsonl(args.primary / "primary-items.jsonl")
    dates: dict[str, str] = {}
    for path in args.dates:
        dates |= json.loads(path.read_text())
    return [item_from(r) for r in records], {r["question_id"]: r["repo"] for r in records}, dates


def run_invent(args: argparse.Namespace) -> dict:
    """Spark-invented situations for every pre-cutoff lesson (template text only)."""
    from plug_r4_spark import invent_one, run_all, session  # noqa: PLC0415

    spark = session(args.run_cap_usd)
    rows = _read_jsonl(args.out / "lessons.jsonl")
    lessons = [Lesson(**{**r, "added": tuple(r["added"])}) for r in rows]
    return run_all(
        lessons, lambda lesson: invent_one(spark, lesson, INVENT_COUNT), args.out / "invent.jsonl"
    )


def repo_queries(queries: list, repo_of: dict, repo: str) -> list:
    """The primary queries of one repository."""
    return [q for q in queries if repo_of[q["question_id"].split("::")[0]] == repo]


def run_rows(args: argparse.Namespace) -> dict:
    """Train and valid rows per scored repository, and its primary queries."""
    items, repo_of, _ = load_primary(args)
    lessons = [
        Lesson(**{**r, "added": tuple(r["added"])})
        for r in _read_jsonl(args.cont / "lessons.jsonl")
    ]
    invented = accepted(args.cont / "invent.jsonl", "situations")
    labels = {
        r["pair_id"]: r["label"] for r in _read_jsonl(args.cont / "labels.jsonl") if "label" in r
    }
    scores = {r["question_id"]: r["p_yes"] for r in _read_jsonl(args.pair_scores)}
    pairs = _read_jsonl(args.cont / "pairs.jsonl")
    general = _read_jsonl(args.work / "rows" / "train.jsonl")
    misses = near_misses(args.work)
    habits = _read_jsonl(args.habits)
    queries = _read_jsonl(args.primary / "primary-queries.jsonl")
    sizes: dict[str, int] = {}
    idle: list[str] = []
    for repo in sorted(set(repo_of.values())):
        store = [x for x in lessons if x.repo == repo]
        if not store:  # nothing learned before the cutoff: this repository reads the general judge
            idle.append(repo)
            continue
        picks = repo_picks(repo, store, lessons)
        labeled = labeled_rows([p for p in pairs if p["repo"] == repo], labels, scores)
        rows = repo_rows(picks, invented, misses, labeled, general)
        folder = args.out / "habits10" / slug(repo)
        _jsonl(folder / "train.jsonl", rows)
        mine = repo_queries(queries, repo_of, repo)
        _jsonl(args.out / "queries" / f"{slug(repo)}.jsonl", mine)
        sizes[slug(repo)] = len(rows)
    add_habits(args.out, habits, 0.15)
    (args.out / "no-adapter-repos.json").write_text(json.dumps(idle))
    return {"repos_trained": len(sizes), "repos_without_lessons": len(idle)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("prep", "invent", "rows"))
    for flag in ("--primary", "--work", "--spark", "--cont", "--pair-scores", "--habits", "--out"):
        parser.add_argument(flag, type=Path)
    parser.add_argument("--pool", type=Path, nargs="*")
    parser.add_argument("--dates", type=Path, nargs="*")
    parser.add_argument("--run-cap-usd", type=float)
    args = parser.parse_args()
    stage = {"prep": run_prep, "invent": run_invent, "rows": run_rows}[args.stage]
    print(json.dumps(stage(args)))


if __name__ == "__main__":
    main()
