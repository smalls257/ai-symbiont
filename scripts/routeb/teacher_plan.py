"""Pick the earlier tasks for Spark teacher runs, hardest first: every collection task plain
Glimmer does not already pass reliably (2+ graded plain runs, all resolved), never a test task.

Writes the sqlglot candidates (CAL2 jsonl) and a Django task file holding only the chosen
history tasks (the Django driver reads its phase list from data/swev-django-tasks.json).
Usage: python teacher_plan.py --test-set T --django-tasks D --plain-log L [...] --out DIR
"""

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

RELIABLE_RUNS = 2  # owner: skip tasks plain Glimmer already passes reliably


def plain_record(logs: Iterable[Path]) -> dict[str, list[int]]:
    """Per task [solved, graded] over plain runs without an error."""
    found: dict[str, list[int]] = {}
    for log in logs:
        for line in log.read_text().splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("resolved") is None or row.get("error_kind"):
                continue
            if row.get("arm") not in (None, "plain"):
                continue
            cell = found.setdefault(row["instance_id"], [0, 0])
            cell[0] += bool(row["resolved"])
            cell[1] += 1
    return found


def reliable(record: list[int] | None) -> bool:
    """Plain solved every one of at least RELIABLE_RUNS graded runs."""
    return record is not None and record[1] >= RELIABLE_RUNS and record[0] == record[1]


def plain_rate(record: list[int] | None) -> float:
    """Plain solve rate; a task never graded counts as unsolved (hardest first)."""
    return record[0] / record[1] if record and record[1] else 0.0


def plan(test_set: dict, records: dict[str, list[int]]) -> dict[str, list[str]]:
    """Earlier tasks per repo for teacher runs, hardest first; raises on a test-set task."""
    held = {entry["task"] for entry in test_set["test"]}
    chosen = {
        repo: sorted(
            (task for task in tasks if not reliable(records.get(task))),
            key=lambda task: plain_rate(records.get(task)),
        )
        for repo, tasks in test_set["collect"].items()
    }
    leaked = sorted(held & {task for tasks in chosen.values() for task in tasks})
    if leaked:
        raise ValueError(f"test-set tasks in the teacher plan: {leaked}")
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-set", type=Path, required=True)
    parser.add_argument("--django-tasks", type=Path, required=True)
    parser.add_argument("--plain-log", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    chosen = plan(json.loads(args.test_set.read_text()), plain_record(args.plain_log))
    args.out.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps({"instance_id": task}) + "\n" for task in chosen["sqlglot"])
    (args.out / "teacher-sqlglot.jsonl").write_text(lines)
    listed = json.loads(args.django_tasks.read_text())
    keep = set(chosen["django"])
    listed["tasks"] = [t for t in listed["tasks"] if t["instance_id"] in keep]
    (args.out / "swev-django-tasks.json").write_text(json.dumps(listed, indent=1))
    print(json.dumps({repo: len(tasks) for repo, tasks in chosen.items()}))


if __name__ == "__main__":
    main()
