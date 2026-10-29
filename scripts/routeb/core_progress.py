"""Running count of passing earlier-task runs for Core collection, with the owner's midpoint check.

Counts runs graded resolved by the official evaluation in the collection logs plus the reusable
passing runs, and the distinct earlier tasks they cover. At the midpoint (half the planned runs
graded) it flags passes under MIN_PASSES or tasks under MIN_TASKS: the trigger for the Spark
fallback, which only the coordinator starts. Appends one line per call to progress.txt.
Usage: python core_progress.py COLLECT_DIR [--planned 128]
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

MIN_PASSES, MIN_TASKS = 30, 15  # owner's midpoint thresholds
LOGS = ("sqlglot/calibration.jsonl", "django/swev.jsonl")


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def tally(collect: Path) -> dict[str, int]:
    """Graded and passing new runs, all passes (with reusable ones) and distinct tasks covered."""
    rows = [row for log in LOGS for row in _rows(collect / log)]
    graded = [row for row in rows if row.get("resolved") is not None and not row.get("error_kind")]
    new = [row["instance_id"] for row in graded if row["resolved"] is True]
    reused = [
        row["task"] for row in _rows(collect / "reusable-passing.jsonl") if row["arm"] == "plain"
    ]
    return {
        "graded": len(graded),
        "new_passes": len(new),
        "passes": len(new) + len(reused),
        "tasks": len(set(new) | set(reused)),
    }


def verdict(counts: dict[str, int], planned: int) -> str:
    """'midpoint ok', 'MIDPOINT LOW: ...' or 'before midpoint'."""
    if counts["graded"] * 2 < planned:
        return "before midpoint"
    if counts["passes"] < MIN_PASSES or counts["tasks"] < MIN_TASKS:
        low = f"passes {counts['passes']} (min {MIN_PASSES}), tasks {counts['tasks']}"
        return f"MIDPOINT LOW: {low} (min {MIN_TASKS})"
    return "midpoint ok"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("collect", type=Path)
    parser.add_argument("--planned", type=int, default=128)
    args = parser.parse_args()
    counts = tally(args.collect)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    line = (
        f"{stamp} graded {counts['graded']}/{args.planned} passes {counts['passes']} "
        f"(new {counts['new_passes']}) tasks {counts['tasks']} {verdict(counts, args.planned)}"
    )
    with (args.collect / "progress.txt").open("a") as out:
        out.write(line + "\n")
    print(line)


if __name__ == "__main__":
    main()
