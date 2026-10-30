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


def teacher_trajectory(run_dir: Path, row: dict) -> Path:
    """Where the Core teacher driver (control_teacher.py) writes a run's trajectory."""
    return run_dir / "traj" / f"{row['instance_id']}.traj.json"


def model_called(trajectory: Path) -> str:
    """The model the agent actually called, from the trajectory's own config (record fields
    written by a reused driver config can name the default model instead)."""
    config = json.loads(trajectory.read_text())["info"]["config"]
    return str(config["model"]["model_name"])


def passing_runs(run_dir: Path) -> list[dict]:
    """Manifest entries for the resolved runs of one run directory."""
    found = []
    sources = (
        ("calibration.jsonl", cal2_trajectory),
        ("swev.jsonl", swev_trajectory),
        ("runs.jsonl", teacher_trajectory),
    )
    for log, where in sources:
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
                    "run": row.get("run", 1),
                    "arm": row.get("arm") or "plain",
                    "model": (model := model_called(trajectory)),
                    "source": "teacher/spark" if model.startswith("muse-spark") else "glimmer",
                    "passed": True,
                    "steps": row.get("steps") or row.get("agent_steps"),
                    "step_limit": row.get("step_limit"),
                    "prompt_tokens": row.get("prompt_tokens"),
                    "completion_tokens": row.get("completion_tokens"),
                    "run_dir": str(run_dir),
                    "trajectory": str(trajectory),
                }
            )
    return found


def later_candidate_ids(split_check: dict) -> frozenset[str]:
    """Every later candidate of Core D2 (results/core-d2-split-check.json): never trained on."""
    return frozenset(task for repo in split_check.values() for task in repo["keep_ids"])


def manifest(
    test_set: dict, run_dirs: list[Path], later: frozenset[str] = frozenset()
) -> tuple[list[dict], int]:
    """Passing runs of non-test, non-later-candidate tasks, and how many runs were refused.

    All later candidates are refused, not only the 100 test tasks: no run may see them.
    """
    held = {entry["task"] for entry in test_set["test"]} | later
    found = [entry for run_dir in run_dirs for entry in passing_runs(run_dir)]
    kept = [entry for entry in found if entry["task"] not in held]
    return kept, len(found) - len(kept)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-set", type=Path, required=True)
    parser.add_argument(
        "--later-candidates", type=Path, required=True, help="core-d2-split-check.json"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("dirs", type=Path, nargs="+")
    args = parser.parse_args()
    test_set = json.loads(args.test_set.read_text())
    later = later_candidate_ids(json.loads(args.later_candidates.read_text()))
    found, skipped = manifest(test_set, args.dirs, later)
    args.out.write_text("".join(json.dumps(entry) + "\n" for entry in found))
    by = Counter((entry["run_dir"], entry["source"]) for entry in found)
    print(
        json.dumps(
            {
                "refused_test_or_later_candidate_runs": skipped,
                "passing_runs": len(found),
                "tasks": len({e["task"] for e in found}),
                "by_source_arm": {f"{s}:{a}": n for (s, a), n in sorted(by.items())},
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
