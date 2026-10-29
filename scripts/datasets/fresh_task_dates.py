"""The creation date of every task in the fresh export list, from SWE-rebench at the pinned
revision, so Plug round 4 can split each repository's sessions by time. Dates and ids only.

Usage: uv run --with duckdb python scripts/datasets/fresh_task_dates.py --fresh fresh-pool.json
Usage:   --out task-dates.json

A task without a date in SWE-rebench raises: a session that cannot be placed in time cannot be
called earlier or later.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import export_nebius_sqlglot as single  # noqa: E402
from export_nebius_repos import REBENCH, REBENCH_FILES  # noqa: E402

# The exporter reads two files for its held-out repos; fresh tasks also sit in the test split's
# other half, at the same pinned revision.
DATE_FILES = (*REBENCH_FILES, "test-00000-of-00002")


def dates_of(tasks: set[str]) -> dict[str, str]:
    """created_at of each wanted task, the first one found across the pinned files."""
    db = single._connect()
    found: dict[str, str] = {}
    for name in DATE_FILES:
        rows = single._with_rate_limit_backoff(
            "reading task dates",
            lambda name=name: db.execute(
                f"SELECT instance_id, CAST(created_at AS VARCHAR) FROM '{REBENCH.format(name)}'"
            ).fetchall(),
        )
        for task, created in rows:
            if task in tasks:
                found.setdefault(task, created)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fresh", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    listed = json.loads(args.fresh.read_text())["repos"]
    tasks = {task for entry in listed for task in entry["tasks"]}
    found = dates_of(tasks)
    missing = sorted(tasks - set(found))
    if missing:
        raise SystemExit(f"{len(missing)} task(s) without a SWE-rebench date, e.g. {missing[:3]}")
    args.out.write_text(json.dumps(dict(sorted(found.items())), indent=1))
    print(json.dumps({"tasks": len(found)}))


if __name__ == "__main__":
    main()
