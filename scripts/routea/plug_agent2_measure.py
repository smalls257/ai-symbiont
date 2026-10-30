"""PLUG-AGENT-2 smoke reading: the none arm's conditional repeat share, from trajectories.

Primary indicator per run (arm-blind): among runs with a first known mistake, did the same key fail
again after it. Known = the key of a lesson labeled `applies` for the task (same repository). Prints
counts, the share and the empty-key share; keys are printed only with --top, to the terminal.
Usage: python plug_agent2_measure.py <labels.jsonl> <stores.json> <traj-dir>... [--top N]
"""

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from plug_agent2_branchpoint import find_branch_point, occurrences_after
from plug_agent2_keys import Key, RunReading, failures_in, key_of, read_run
from plug_agent_notes import Failure

from symbiont.miner.commands import normalise_command

WINDOW = 15  # model calls after the first known mistake, as in the branches
PROBE_POINTS = 5  # restored probe points with 3 none branches each
STOP_MIN_RUNS = (
    10  # smoke go/no-go (frozen in the prereg): at least this many runs with a first known mistake
)
STOP_MIN_SHARE = 0.30  # and at least this share of them repeating it


def lesson_key(lesson: dict) -> Key | None:
    """The lesson's failure key under the frozen rule, or None when it has no usable key."""
    program, target = normalise_command(lesson["failed"])
    return key_of(Failure(lesson["failed"], lesson["error"], program, target))


def known_keys(labels: dict[str, str], lessons: list[dict]) -> frozenset[Key]:
    """Keys of the task's `applies` lessons that have a usable key."""
    keys = (lesson_key(x) for x in lessons if labels.get(x["lesson_id"]) == "applies")
    return frozenset(key for key in keys if key is not None)


def task_of(path: Path) -> str:
    return path.name.removesuffix(".traj.json")


def windowed(reading: RunReading, messages: list[dict], known: frozenset[Key]) -> RunReading:
    """The reading with `repeated` set to the natural repeat in the source run: the first known
    line occurs again within W = 15 model calls of the point (descriptive; the stop rule uses the
    none-arm probe, not this)."""
    point = find_branch_point(messages, known)
    within = point is not None and occurrences_after(messages, point, WINDOW) >= 2
    return replace(reading, repeated=within)


def read_trajectories(labels: dict, stores: dict, directories: list[Path]) -> tuple[list, Counter]:
    """(task, RunReading) per labeled run and the keyed failures' frequencies."""
    readings, frequency = [], Counter()
    for directory in directories:
        for path in sorted(directory.glob("*.traj.json")):
            task = task_of(path)
            if task not in labels:
                continue
            messages = json.loads(path.read_text())["messages"]
            fails = failures_in(messages)
            frequency.update(key for key in map(key_of, filter(None, fails)) if key is not None)
            known = known_keys(labels[task], stores[task]["lessons"])
            readings.append((task, windowed(read_run(fails, known), messages, known)))
    return readings, frequency


def ratio(part: int, whole: int) -> float | None:
    """part / whole rounded, None when there is no whole."""
    return round(part / whole, 3) if whole else None


def probe_share(points: list[list[bool]]) -> float | None:
    """Mean over probe points of the share of none branches in which the line occurs again."""
    return (
        sum(sum(branches) / len(branches) for branches in points) / len(points) if points else None
    )


def go_ahead(valid_points: int, share: float | None) -> bool:
    """The frozen stop rule's probe part: enough restored probe points and a none-arm occurrence
    share high enough that a note has something to prevent."""
    return share is not None and valid_points >= PROBE_POINTS and share >= STOP_MIN_SHARE


def summary_of(readings: list) -> dict:
    """Counts, the conditional repeat share and the go/no-go verdict of the frozen stop rule."""
    runs = [run for _, run in readings]
    conditioned = [(task, run) for task, run in readings if run.first_known is not None]
    repeated = sum(run.repeated for _, run in conditioned)
    share = ratio(repeated, len(conditioned))
    return {
        "runs": len(runs),
        "runs_with_failures": sum(run.failures > 0 for run in runs),
        "failures": sum(run.failures for run in runs),
        "keyless_share": ratio(sum(run.keyless for run in runs), sum(run.failures for run in runs)),
        "runs_with_first_known": len(conditioned),
        "tasks_with_first_known": len({task for task, _ in conditioned}),
        "repeated_after_first_known": repeated,
        "conditional_repeat_share": share,
        "any_key_repeats_per_run": ratio(sum(run.any_key_repeats for run in runs), len(runs)),
    }


def probe_summary(records_path: Path) -> dict:
    """The stop rule's probe reading: valid points (no void), the none-arm occurrence share."""
    records = [json.loads(line) for line in records_path.read_text().splitlines()]
    points = [
        [b["repeated"] for b in r["branches"] if b["arm"] == "none"]
        for r in records
        if "void" not in r and r.get("branches")
    ]
    share = probe_share(points)
    return {
        "records": len(records),
        "valid_points": len(points),
        "voids": sum("void" in r for r in records),
        "none_occurrence_share": None if share is None else round(share, 3),
        "go": go_ahead(len(points), share),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("stores", type=Path)
    parser.add_argument("trajs", type=Path, nargs="+")
    parser.add_argument("--top", type=int, default=0)
    parser.add_argument("--probe", type=Path, default=None, help="probe records (JSON lines)")
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe_summary(args.probe), indent=1))
        return
    rows = map(json.loads, args.labels.read_text().splitlines())
    labels = {row["task"]: row["labels"] for row in rows if "labels" in row}
    readings, frequency = read_trajectories(labels, json.loads(args.stores.read_text()), args.trajs)
    print(json.dumps(summary_of(readings), indent=1))
    if args.top:
        print(frequency.most_common(args.top))


if __name__ == "__main__":
    main()
