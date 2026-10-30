"""Core D2 report: the two co-primaries, the claim, the early-stop check and the run accounting.

Reads a test run's directory (runs.jsonl, voids.jsonl, dropped.jsonl, voided_blocks.jsonl) and
prints ids-free counts: A minus P and A minus C with bootstrap intervals over complete tasks,
whether both lower bounds clear 0, whether the early stop is due, and per-arm and per-server
void, drop and incomplete-task counts. Descriptive secondaries are not computed here.
Usage: python core2_report.py --test-set T --out DIR [--arms P A C]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from core2_test_plan import (
    Arm,
    claim_holds,
    co_primaries,
    complete_tasks,
    early_stop_due,
)
from core2_test_run import graded_runs, read_jsonl


def accounting(out: Path, test_ids: list[str], arms: frozenset[Arm]) -> dict:
    """Voids, drops and incomplete tasks, per arm and per server."""
    voids = read_jsonl(out / "voids.jsonl")
    dropped = read_jsonl(out / "dropped.jsonl")
    returned = read_jsonl(out / "voided_blocks.jsonl")
    complete = set(complete_tasks(graded_runs(out), test_ids, arms))
    return {
        "void_runs_by_arm": dict(Counter(row["arm"] for row in voids)),
        "void_runs_by_server": dict(Counter(row["server"] for row in voids)),
        "dropped_tasks": len({row["instance_id"] for row in dropped}),
        "dropped_by_server": dict(Counter(row["server"] for row in dropped)),
        "blocks_returned_by_server": dict(Counter(row["server"] for row in returned)),
        "complete_tasks": len(complete),
        "incomplete_tasks": len(test_ids) - len(complete),
    }


def report(out: Path, test_ids: list[str], arms: frozenset[Arm]) -> dict:
    """Everything the report prints, as one dictionary."""
    records = graded_runs(out)
    result = co_primaries(records, test_ids, arms)
    return {
        "co_primaries": {
            name: dict(zip(("mean", "low", "high"), vals, strict=True))
            for name, vals in result.items()
        },  # fmt: skip
        "claim_holds": claim_holds(result),
        "early_stop_due": early_stop_due(records, test_ids, arms),
        "early_stopped": (out / "early_stop.json").is_file(),
        **accounting(out, test_ids, arms),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-set", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arms", nargs="+", default=["P", "A", "C"], choices=[str(a) for a in Arm])
    args = parser.parse_args()
    test_ids = json.loads(args.test_set.read_text())["test"]
    print(json.dumps(report(args.out, test_ids, frozenset(Arm(a) for a in args.arms)), indent=1))


if __name__ == "__main__":
    main()
