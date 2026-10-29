"""List passing earlier-task runs for Route B training: task, run, steps, tokens, trajectory.

Reads CAL2 logs (calibration.jsonl) and SWE-bench Django logs (swev.jsonl) under the given run
directories. Only runs graded resolved by the official evaluation are kept; a missing trajectory
raises; runs of test-set tasks are left out and their count is printed, never kept.
Usage: python core_collect_manifest.py --test-set results/core-test-set.json --out M DIR [DIR ...]
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def cal2_trajectory(run_dir: Path, row: dict) -> Path:
    """Where CAL2 writes a run's trajectory."""
    name = f"{row['stage']}-run{row['run']}-{row['reasoning']}.traj.json"
    return run_dir / "traj" / row["instance_id"] / name


def swev_trajectory(run_dir: Path, row: dict) -> Path:
    """Where the SWE-bench Django driver writes a run's trajectory."""
    name = f"{row['phase']}-{row['arm']}-run{row['run']}-cap{row['step_limit']}.traj.json"
    return run_dir / "traj" / row["instance_id"] / name


def passing_runs(run_dir: Path) -> list[dict]:
    """Manifest entries for the resolved runs of one run directory."""
    found = []
    for log, where in (("calibration.jsonl", cal2_trajectory), ("swev.jsonl", swev_trajectory)):
        if not (run_dir / log).is_file():
            continue
        for row in _rows(run_dir / log):
            if row.get("resolved") is not True:
                continue
            trajectory = where(run_dir, row)
            if not trajectory.is_file():
                raise FileNotFoundError(f"resolved run without a trajectory: {trajectory}")
            found.append(
                {
                    "task": row["instance_id"],
                    "run": row["run"],
                    "arm": row.get("arm") or "plain",
                    "model": row.get("model"),
                    "source": f"teacher/{row['teacher']}" if row.get("teacher") else "glimmer",
                    "passed": True,
                    "steps": row.get("steps"),
                    "step_limit": row.get("step_limit"),
                    "prompt_tokens": row.get("prompt_tokens"),
                    "completion_tokens": row.get("completion_tokens"),
                    "run_dir": str(run_dir),
                    "trajectory": str(trajectory),
                }
            )
    return found


def manifest(test_set: dict, run_dirs: list[Path]) -> tuple[list[dict], int]:
    """Passing runs of non-test tasks, and how many test-set runs were left out (always printed)."""
    held = {entry["task"] for entry in test_set["test"]}
    found = [entry for run_dir in run_dirs for entry in passing_runs(run_dir)]
    kept = [entry for entry in found if entry["task"] not in held]
    return kept, len(found) - len(kept)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-set", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("dirs", type=Path, nargs="+")
    args = parser.parse_args()
    test_set = json.loads(args.test_set.read_text())
    found, skipped = manifest(test_set, args.dirs)
    args.out.write_text("".join(json.dumps(entry) + "\n" for entry in found))
    by = Counter((entry["run_dir"], entry["source"]) for entry in found)
    print(
        json.dumps(
            {
                "skipped_test_set_runs": skipped,
                "passing_runs": len(found),
                "tasks": len({e["task"] for e in found}),
                "by_source_arm": {f"{s}:{a}": n for (s, a), n in sorted(by.items())},
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
