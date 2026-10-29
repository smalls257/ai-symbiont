"""CAL2 command lines and logs for the coding plugin, and the mined-evidence filter (pure).

`mined_evidence` keeps only allow-listed loop runs and plain-history runs outside the judged-only
baseline half, then checks again: a judged task in lesson evidence raises.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Sequence
from pathlib import Path

from attempts import Attempt, Outcome, Split, refuse_baseline_tasks
from general_evidence import Evidence
from general_runs import PLAIN_LOGS
from utility import in_baseline

PLAIN_GLIMMER = "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"
STEP_LIMIT, WALL_LIMIT_MIN, WORKERS = 50, 45, 4  # the general pilot's settings


@dataclasses.dataclass(frozen=True)
class CodingPaths:
    """The CAL2 workdir (data/, calibration-v2/launch.py, the plain logs), split and clone."""

    workdir: Path
    split: Path
    clone: Path
    python: str = "python"


def slug(model: str) -> str:
    """A model name as a directory name."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", model)


def mined_evidence(evidence: Evidence, allowed: frozenset[str]) -> Evidence:
    """Evidence a harvest may use: allow-listed loop runs and plain history, no judged task."""
    runs = tuple(
        run
        for run in evidence.runs
        if f"{run.facts.run_id}/{run.task}" in allowed
        or (run.log in PLAIN_LOGS and not in_baseline(run.task))
    )
    tasks = {task: row for task, row in evidence.tasks.items() if not in_baseline(task)}
    refuse_baseline_tasks([run.task for run in runs] + list(tasks), "lesson evidence")
    return dataclasses.replace(evidence, runs=runs, tasks=tasks)


def cal2_command(paths: CodingPaths, model: str, runs_dir: str, lessons: Path | None) -> list[str]:
    """The CAL2 launch line for one batch: one run per task, the round's model by name."""
    argv = [paths.python, "-u", "calibration-v2/launch.py", str(paths.workdir),
            "--runs-dir", runs_dir, "--candidates-log", f"{runs_dir}/tasks.jsonl",
            "--fixed-runs", "1", "--workers", str(WORKERS), "--step-limit", str(STEP_LIMIT),
            "--wall-limit-min", str(WALL_LIMIT_MIN)]  # fmt: skip
    if model != PLAIN_GLIMMER:
        argv += ["--model", model]
    return argv + (["--lessons", str(lessons)] if lessons else [])


def attempt_log(attempt: Attempt) -> str:
    """The runs-dir an attempt was logged in (its id is <runs-dir>/<run name>/<task>)."""
    return attempt.attempt_id.rsplit("/", 2)[0]


def attempts_from_log(
    log_dir: Path, runs_dir: str, tasks: Sequence[str], model: str,
    context: tuple[int, Split, frozenset[str]],
) -> list[Attempt]:  # fmt: skip
    """One attempt per task from CAL2's log; a task with no graded record is UNGRADED."""
    round_index, split, trained = context
    path = log_dir / "calibration.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"CAL2 wrote no log at {path}")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    found = []
    for task in tasks:
        graded = [r for r in rows if r["instance_id"] == task and r.get("resolved") is not None]
        if graded:
            rec = graded[-1]
            name = f"{rec['stage']}-run{rec['run']}-{rec['reasoning']}"
            outcome = Outcome.PASSED if rec["resolved"] else Outcome.FAILED
            attempt_id = f"{runs_dir}/{name}/{task}"
        else:
            outcome, attempt_id = Outcome.UNGRADED, f"{runs_dir}/ungraded/{task}"
        found.append(Attempt(attempt_id, task, round_index, model, split, outcome, trained))
    return found
