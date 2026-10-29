"""Plug round 4 feasibility: how many fresh repositories have failures that recur across time.

Usage: uv run python scripts/routea/plug_r4_later.py --fresh F/fresh-pool.json --pool F/pool
Usage:   --dates F/task-dates.json --out F/later-counts.json

Per never-read repository, tasks are ordered by SWE-rebench creation date (ties by id); the
earlier half are the nights, whose lessons enter the store. A later situation is a distinct
(later task, failure key) whose key some earlier lesson has: the stored lesson applies. Runs of
one task are parallel attempts, not later sessions, so a task counts once per key. Counts only.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from build_lessons import _sessions  # noqa: E402
from lessons import lessons_in_session  # noqa: E402
from plug_situation import key_of  # noqa: E402

THRESHOLDS = (1, 2, 3, 4, 6, 8)  # repos with at least this many later situations
# Which earlier lesson "applies" to a later failure, strictest first. `same_fix`: the same error
# class and the same added fix tokens (round 3's key); `shared_fix`: the same error class and at
# least one shared added token; `same_failure`: the same program and error class, fix unchecked.
CRITERIA = ("same_fix", "shared_fix", "same_failure")


def applies(criterion: str, earlier, later) -> bool:
    """Whether an earlier lesson applies to a later one under a criterion."""
    if criterion == "same_fix":
        return key_of(earlier) == key_of(later)
    if criterion == "shared_fix":
        return earlier.error_class == later.error_class and bool(
            set(earlier.added) & set(later.added)
        )
    return (earlier.program, earlier.error_class) == (later.program, later.error_class)


def never_read(fresh: dict) -> set[str]:
    """Repositories no experiment had read before round 4."""
    return {entry["repo"] for entry in fresh["repos"] if not entry["meta2_exported"]}


def keys_by_task(pool: Path, wanted: set[str]) -> dict[str, dict[str, dict]]:
    """repo -> task -> its sessions' lessons by failure key (unreadable files skipped)."""
    found: dict[str, dict[str, dict]] = {}
    unreadable: list[str] = []
    drops: Counter[str] = Counter()
    for session in _sessions(pool, unreadable):
        lessons = lessons_in_session(session, drops)
        if not lessons or lessons[0].repo not in wanted:
            continue
        task = session[0].task_id
        found.setdefault(lessons[0].repo, {}).setdefault(task, {}).update(
            {key_of(lesson): lesson for lesson in lessons}
        )
    return found


def later_situations(tasks: dict[str, dict], dates: dict[str, str]) -> dict[str, int]:
    """Per criterion, later (task, key) pairs an earlier lesson applies to; all later pairs."""
    order = sorted(tasks, key=lambda task: (dates[task], task))
    cut = len(order) // 2
    earlier = [lesson for task in order[:cut] for lesson in tasks[task].values()]
    later = [lesson for task in order[cut:] for lesson in tasks[task].values()]
    found = {
        criterion: sum(any(applies(criterion, e, x) for e in earlier) for x in later)
        for criterion in CRITERIA
    }
    return {**found, "later_pairs": len(later), "tasks": len(order)}


def criterion_summary(counts: dict[str, dict], criterion: str) -> dict:
    """Repos with at least n later situations under one criterion, and the total."""
    found = [c[criterion] for c in counts.values()]
    return {
        "repos_with_at_least": {n: sum(r >= n for r in found) for n in THRESHOLDS},
        "situations": sum(found),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--fresh", "--pool", "--dates", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    wanted = never_read(json.loads(args.fresh.read_text()))
    dates = json.loads(args.dates.read_text())
    by_repo = keys_by_task(args.pool, wanted)
    counts = {repo: later_situations(tasks, dates) for repo, tasks in sorted(by_repo.items())}
    summary = {
        "never_read_repos": len(wanted),
        "repos_with_lessons": len(counts),
        **{criterion: criterion_summary(counts, criterion) for criterion in CRITERIA},
    }
    args.out.write_text(json.dumps({"summary": summary, "per_repo": counts}, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
