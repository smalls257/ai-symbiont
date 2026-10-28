"""Read Glimmer's public sqlglot calibration runs and the public task rows into TaskEvidence.

The IO edge of the sqlglot lesson builder: calibration logs and trajectories copied from the 5080
desktop, the SWE-rebench rows, and a clone of the public sqlglot repo for the source as it was at
each task's base commit. A graded run with no trajectory, or a source file git cannot show, raises
naming the path: a lesson built on a missing file would be a guess.
"""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

from sqlglot_lessons import TaskEvidence, issue_title, test_command
from sqlglot_places import Place, diff_files, places
from sqlglot_runs import RunFacts, run_facts

# The four calibration logs of Glimmer's sqlglot runs; runs-pilot is the lesson arm, never a source.
RUN_LOGS = ("runs", "runs-wide", "runs-cal2", "runs-tier2")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def graded_runs(src: Path) -> Iterator[tuple[str, dict, Path]]:
    """(run id, calibration row, trajectory path) for every graded run in the four logs."""
    for log in RUN_LOGS:
        for row in _jsonl(src / log / "calibration.jsonl"):
            name = f"{row['stage']}-run{row['run']}-{row['reasoning']}"
            trajectory = src / log / "traj" / row["instance_id"] / f"{name}.traj.json"
            if not trajectory.is_file():
                raise FileNotFoundError(f"graded run without a trajectory: {trajectory}")
            yield f"{log}/{name}", row, trajectory


def _submission(trajectory: dict) -> str:
    text = (trajectory.get("info") or {}).get("submission") or ""
    start = text.find("diff --git")
    return text[start:] if start >= 0 else ""


def source_at(clone: Path, commit: str, path: str) -> str:
    """The file's text at `commit`; raises naming the commit and path when git cannot show it."""
    shown = subprocess.run(
        ["git", "-C", str(clone), "show", f"{commit}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        raise FileNotFoundError(f"git show {commit[:10]}:{path}: {shown.stderr.strip()[:200]}")
    return shown.stdout


def places_at(diff: str, clone: Path, commit: str) -> tuple[Place, ...]:
    """Places of a diff's changes to existing source files (new files have no old construct)."""
    created = {line[6:] for line in diff.splitlines() if line.startswith("+++ b/")} - {
        line[6:] for line in diff.splitlines() if line.startswith("--- a/")
    }
    paths = [
        path
        for path in diff_files(diff)
        if path.startswith("sqlglot/") and path.endswith(".py") and path not in created
    ]
    return tuple(places(diff, {path: source_at(clone, commit, path) for path in paths}))


def task_evidence(row: dict, runs: list[tuple[RunFacts, str]], clone: Path) -> TaskEvidence:
    """One task's evidence; `runs` pairs each run's facts with its submitted diff."""
    solved = next((diff for facts, diff in runs if facts.resolved and diff), "")
    return TaskEvidence(
        task=row["instance_id"],
        title=issue_title(row["problem_statement"]),
        created=row["created_at"],
        test=test_command(row["FAIL_TO_PASS"]),
        gold_places=places_at(row["patch"], clone, row["base_commit"]),
        runs=tuple(facts for facts, _ in runs),
        solved_places=places_at(solved, clone, row["base_commit"]) if solved else (),
    )


def load_evidence(src: Path, task_rows: Path, clone: Path) -> dict[str, TaskEvidence]:
    """Evidence for every task Glimmer attempted, keyed by instance id."""
    rows = {row["instance_id"]: row for row in json.loads(task_rows.read_text(encoding="utf-8"))}
    by_task: dict[str, list[tuple[RunFacts, str]]] = {}
    for run_id, result, path in graded_runs(src):
        trajectory = json.loads(path.read_text(encoding="utf-8"))
        facts = run_facts(result, run_id, trajectory["messages"])
        by_task.setdefault(result["instance_id"], []).append((facts, _submission(trajectory)))
    return {task: task_evidence(rows[task], runs, clone) for task, runs in by_task.items()}


def gold_patches(task_rows: Path, tasks: tuple[str, ...]) -> dict[str, str]:
    """The public gold patch of each named task; raises KeyError for a task with no row."""
    rows = {row["instance_id"]: row for row in json.loads(task_rows.read_text(encoding="utf-8"))}
    return {task: rows[task]["patch"] for task in tasks}
