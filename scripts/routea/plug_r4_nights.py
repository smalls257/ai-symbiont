"""Plug round 4 counts on the long-history repositories: lessons per night and later situations.

Usage: uv run python scripts/routea/plug_r4_nights.py --list L/long-pool.json --pool L/pool
Usage:   --dates L/task-dates.json --out L/night-counts.json

Per repository, tasks are ordered by SWE-rebench creation date (ties by id); the first two thirds
are split into NIGHTS contiguous nights, the last third are the later sessions. Lessons accumulate
night by night. A later situation is a distinct (later task, failure key); it is a pick situation
under a criterion (`plug_r4_later.applies`) when a lesson stored by night 10 applies, else a
silence situation. Counts only, decided before any model answers.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_r4_later import applies, keys_by_task  # noqa: E402

NIGHTS = 10
REPORTED_NIGHTS = (1, 5, 10)
LATER_SHARE = 1 / 3
CRITERIA = ("same_fix", "shared_fix")  # primary, then the pre-declared fallback


def nights_and_later(tasks: dict[str, dict], dates: dict[str, str]) -> tuple[list[list], list]:
    """The tasks of each night (earliest first) and the later tasks."""
    order = sorted(tasks, key=lambda task: (dates[task], task))
    cut = len(order) - max(1, round(len(order) * LATER_SHARE))
    earlier = order[:cut]
    bounds = [round(i * len(earlier) / NIGHTS) for i in range(NIGHTS + 1)]
    return [earlier[bounds[i] : bounds[i + 1]] for i in range(NIGHTS)], order[cut:]


def repo_counts(tasks: dict[str, dict], dates: dict[str, str]) -> dict:
    """Lessons stored by nights 1, 5 and 10, and later pick situations per criterion."""
    nights, later_tasks = nights_and_later(tasks, dates)
    stored: dict = {}
    by_night = {}
    for number, night in enumerate(nights, start=1):
        for task in night:
            stored.update(tasks[task])
        if number in REPORTED_NIGHTS:
            by_night[number] = len(stored)
    later = [lesson for task in later_tasks for lesson in tasks[task].values()]
    picks = {
        criterion: sum(any(applies(criterion, e, x) for e in stored.values()) for x in later)
        for criterion in CRITERIA
    }
    return {"lessons_by_night": by_night, "later_situations": len(later), **picks}


def set_summary(counts: dict[str, dict]) -> dict:
    """Totals and repos with at least one pick situation, per criterion."""
    return {
        "repos_with_lessons": len(counts),
        "lessons_at_night_10": sorted(c["lessons_by_night"][NIGHTS] for c in counts.values()),
        "later_situations": sum(c["later_situations"] for c in counts.values()),
        **{
            criterion: {
                "pick_situations": sum(c[criterion] for c in counts.values()),
                "repos_with_a_pick": sum(c[criterion] > 0 for c in counts.values()),
            }
            for criterion in CRITERIA
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--list", "--pool", "--dates", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    entries = json.loads(args.list.read_text())["repos"]
    dates = json.loads(args.dates.read_text())
    by_repo = keys_by_task(args.pool, {entry["repo"] for entry in entries})
    document = {}
    for name in ("scored", "validation"):
        repos = sorted(e["repo"] for e in entries if e["set"] == name and e["repo"] in by_repo)
        counts = {repo: repo_counts(by_repo[repo], dates) for repo in repos}
        document[name] = {"summary": set_summary(counts), "per_repo": counts}
    args.out.write_text(json.dumps(document, indent=1))
    print(json.dumps({name: part["summary"] for name, part in document.items()}))


if __name__ == "__main__":
    main()
