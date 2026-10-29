"""Read Glimmer's plain sqlglot runs (no lesson, no adapter) from the four calibration logs.

The lesson-arm and adapter-arm logs (runs-pilot, runs-routeb-eval) are never read: their behavior
was steered by a task-specific lesson. A graded run without its trajectory raises naming the path.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlglot_runs import SUBMIT, RunFacts, run_facts, steps_from_messages

PLAIN_LOGS = ("runs", "runs-wide", "runs-cal2", "runs-tier2")


@dataclass(frozen=True)
class PlainRun:
    """One graded plain run: its calibration row's outcome and the facts of its trajectory."""

    task: str
    log: str
    step_limit: int
    resolved: bool
    exit_status: str
    submitted: bool
    facts: RunFacts
    commands: tuple[str, ...]  # bash command strings only, never their output


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def plain_runs(src: Path) -> Iterator[PlainRun]:
    """Every graded run in the plain logs under `src`, in log order."""
    for log in PLAIN_LOGS:
        for row in _rows(src / log / "calibration.jsonl"):
            if row.get("resolved") is None:
                continue
            name = f"{row['stage']}-run{row['run']}-{row['reasoning']}"
            path = src / log / "traj" / row["instance_id"] / f"{name}.traj.json"
            if not path.is_file():
                raise FileNotFoundError(f"graded run without a trajectory: {path}")
            messages = json.loads(path.read_text(encoding="utf-8"))["messages"]
            yield PlainRun(
                task=row["instance_id"],
                log=log,
                step_limit=int(row["step_limit"]),
                resolved=bool(row["resolved"]),
                exit_status=str(row.get("exit_status")),
                submitted=bool(row.get("submitted")),
                facts=run_facts(row, f"{log}/{name}", messages),
                commands=tuple(
                    s.command for s in steps_from_messages(messages) if SUBMIT not in s.command
                ),
            )


def task_rows(path: Path) -> dict[str, dict]:
    """The public SWE-rebench sqlglot rows by instance id."""
    return {row["instance_id"]: row for row in json.loads(path.read_text(encoding="utf-8"))}
