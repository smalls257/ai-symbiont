"""Minimum detectable effect of the Core paired design from plain Glimmer's run-to-run variability.

Per task, adapter mean minus plain mean over r runs each has variance 2v/r, where v is the
mean over tasks of p(1-p) (assumes a constant shift, no treatment heterogeneity). The test is the
mean over n tasks: MDE = (z_{1-alpha/2} + z_power) * sqrt(2v / (r n)).
Usage: python core_mde.py --plain-log L [--plain-log L ...] --tasks T [--pair A B]
"""

import argparse
import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from statistics import NormalDist

ALPHA, POWER = 0.05, 0.8  # owner's check


def z_sum(alpha: float = ALPHA, power: float = POWER) -> float:
    """The two-sided normal quantile at alpha plus the one at the target power."""
    return NormalDist().inv_cdf(1 - alpha / 2) + NormalDist().inv_cdf(power)


def mde(variance: float, tasks: int, runs: int) -> float:
    """Minimum detectable difference in solve rate for the paired design."""
    return z_sum() * math.sqrt(2 * variance / (runs * tasks))


def runs_needed(variance: float, tasks: int, target: float) -> int:
    """Runs per arm per task for an MDE of `target` at `tasks` tasks."""
    return math.ceil(2 * variance * (z_sum() / target) ** 2 / tasks)


def repeat_variance(records: dict[str, list[int]]) -> tuple[float, int]:
    """Mean unbiased p(1-p) over tasks with 2+ runs at one cap, and how many tasks that is."""
    found = [s * (n - s) / (n * (n - 1)) for s, n in records.values() if n >= 2]
    return (sum(found) / len(found), len(found)) if found else (float("nan"), 0)


def pair_variance(first: dict[str, bool], second: dict[str, bool]) -> tuple[float, int]:
    """p(1-p) from two runs per task: discordant pairs / (2 * tasks)."""
    shared = sorted(set(first) & set(second))
    discordant = sum(first[task] != second[task] for task in shared)
    return discordant / (2 * len(shared)), len(shared)


def records_by_cap(logs: Iterable[Path], tasks: set[str]) -> dict[int, dict[str, list[int]]]:
    """[solved, runs] per task per step cap, plain-arm graded runs of the listed tasks only."""
    found: dict[int, dict[str, list[int]]] = {}
    for log in logs:
        for line in log.read_text().splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("instance_id") not in tasks or row.get("resolved") is None:
                continue
            if row.get("arm") not in (None, "plain"):
                continue
            cell = found.setdefault(int(row["step_limit"]), {}).setdefault(
                row["instance_id"], [0, 0]
            )
            cell[0] += bool(row["resolved"])
            cell[1] += 1
    return found


def _solved(log: Path) -> dict[str, bool]:
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return {
        row["instance_id"]: bool(row["resolved"]) for row in rows if row.get("resolved") is not None
    }


def table(variances: Sequence[tuple[str, float, int]], tasks: int) -> dict:
    """Per variance source: MDE at 2 and 4 runs per arm, runs per arm for 5 and 10 points."""
    return {
        label: {
            "v": round(variance, 3),
            "tasks_measured": count,
            "mde_2_runs": round(mde(variance, tasks, 2), 3),
            "mde_4_runs": round(mde(variance, tasks, 4), 3),
            "runs_per_arm_for_5pts": runs_needed(variance, tasks, 0.05),
            "runs_per_arm_for_10pts": runs_needed(variance, tasks, 0.10),
        }
        for label, variance, count in variances
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plain-log", type=Path, action="append", required=True)
    parser.add_argument("--tasks", type=Path, required=True, help="core-test-set.json")
    parser.add_argument("--pair", type=Path, nargs=2, help="two one-run-per-task plain logs")
    parser.add_argument("--n", type=int, default=45)
    args = parser.parse_args()
    test = json.loads(args.tasks.read_text())["test"]
    sqlglot = {entry["task"] for entry in test if entry["repo"] == "sqlglot"}
    rows = [
        (f"repeats at cap {cap}", *repeat_variance(cells))
        for cap, cells in sorted(records_by_cap(args.plain_log, sqlglot).items())
    ]
    if args.pair:
        rows.append(
            ("run 1 vs run 2", *pair_variance(_solved(args.pair[0]), _solved(args.pair[1])))
        )
    print(json.dumps(table(rows, args.n), indent=1))


if __name__ == "__main__":
    main()
