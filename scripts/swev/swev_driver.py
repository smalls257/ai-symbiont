"""Driver for the Django run: one phase, its arms, N runs per task, resumable, two Glimmer slots.

Task-major order (task, run, arm), so a stop leaves finished tasks paired across arms. The log
is append-only and keyed by (task, phase, arm, run, step limit); 3 ungraded runs in a row block.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from swev_run import Arm, Setting, Slot, run_once

WORKERS = 2  # the Glimmer server has 2 slots
MAX_ATTEMPTS = 3
MAX_UNGRADED_IN_A_ROW = 3
PILOT = "pilot"
ANNOUNCED = ("instance_id", "phase", "arm", "run", "exit_status", "steps", "resolved", "wall_s")


class BlockedError(RuntimeError):
    """Too many ungraded runs in a row: Glimmer or docker is down."""


@dataclass(frozen=True)
class Job:
    """One (task, slot) to make sure of."""

    instance_id: str
    slot: Slot


def phase_ids(listed: dict, phase: str) -> list[str]:
    """Task ids of a phase in date order; the pilot is the task list's pilot_ids."""
    if phase == PILOT:
        return list(listed["pilot_ids"])
    ids = [task["instance_id"] for task in listed["tasks"] if task["phase"] == phase]
    if not ids:
        raise ValueError(f"no tasks in phase {phase!r}")
    return ids


def schedule(ids: list[str], phase: str, arms: list[Arm], runs: int) -> list[Job]:
    """Task-major order: every arm's run r of a task before run r+1, every task before the next."""
    return [
        Job(iid, Slot(phase, arm, run)) for iid in ids for run in range(1, runs + 1) for arm in arms
    ]


def record_key(rec: dict) -> tuple:
    """The resume key of a record."""
    return (rec["instance_id"], rec["phase"], rec["arm"], rec["run"], rec["step_limit"])


def job_key(job: Job, setting: Setting) -> tuple:
    """The resume key a job's record will carry."""
    slot = job.slot
    return (job.instance_id, slot.phase, str(slot.arm), slot.run, setting.step_limit)


def mean_of(records: list[dict], field: str) -> float | None:
    """Mean of a numeric field over records (missing counts as 0); None for no records."""
    if not records:
        return None
    return round(sum(rec.get(field) or 0 for rec in records) / len(records), 1)


def arm_totals(records: list[dict], arm: str) -> dict:
    """Counts for one arm: records, graded, resolved, mean steps and wall time of graded runs."""
    mine = [rec for rec in records if rec["arm"] == arm]
    graded = [rec for rec in mine if rec["resolved"] is not None]
    return {
        "records": len(mine),
        "graded": len(graded),
        "resolved": sum(rec["resolved"] for rec in graded),
        "mean_steps": mean_of(graded, "steps"),
        "mean_wall_s": mean_of(graded, "wall_s"),
    }


def per_task(records: list[dict], ids: list[str]) -> list[dict]:
    """Per task and arm: (solved, graded) runs."""
    table = []
    for iid in ids:
        entry: dict = {"instance_id": iid}
        for rec in records:
            if rec["instance_id"] == iid and rec["resolved"] is not None:
                solved, graded = entry.get(rec["arm"], (0, 0))
                entry[rec["arm"]] = (solved + rec["resolved"], graded + 1)
        table.append(entry)
    return table


class SwevDriver:
    """Runs one phase's schedule WORKERS at a time; appends every record; rewrites the summary."""

    def __init__(self, workdir: Path, runs_dir: Path, jobs: list[Job], setting: Setting):
        self.rows = {
            r["instance_id"]: r for r in json.loads((workdir / "data/django_rows.json").read_text())
        }
        self.jobs, self.setting, self.runs_dir = jobs, setting, runs_dir
        runs_dir.mkdir(parents=True, exist_ok=True)
        self.log = runs_dir / "swev.jsonl"
        self.summary_path = runs_dir / "swev-summary.json"
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        self.records = [json.loads(line) for line in lines if line]
        self.state = {"status": "running", "started": time.time()}
        self.ungraded_in_a_row = 0
        self.blocked: str | None = None
        self._lock = threading.Lock()

    def graded(self, job: Job) -> dict | None:
        """The graded record of a job, if one exists."""
        key = job_key(job, self.setting)
        found = (r for r in self.records if record_key(r) == key and r["resolved"] is not None)
        return next(found, None)

    def ensure(self, job: Job) -> None:
        """Make sure the job has a graded record (up to MAX_ATTEMPTS tries)."""
        if self.graded(job):
            return
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self.blocked:
                raise BlockedError(self.blocked)
            rec = run_once(
                self.rows[job.instance_id], job.slot, self.setting, self.runs_dir / "traj"
            )
            self.append(rec | {"attempt": attempt})
            if rec["resolved"] is not None:
                return

    def append(self, rec: dict) -> None:
        """Log, announce and summarize one record; block after too many ungraded in a row."""
        with self._lock:
            self.records.append(rec)
            with self.log.open("a") as handle:
                handle.write(json.dumps(rec) + "\n")
            print(json.dumps({key: rec.get(key) for key in ANNOUNCED}), flush=True)
            graded = rec["resolved"] is not None
            self.ungraded_in_a_row = 0 if graded else self.ungraded_in_a_row + 1
            self.write_summary()
            if self.ungraded_in_a_row >= MAX_UNGRADED_IN_A_ROW:
                self.blocked = f"{self.ungraded_in_a_row} ungraded runs in a row: {rec['error']}"
                raise BlockedError(self.blocked)

    def run(self) -> None:
        """Every job, WORKERS at a time; the final summary is written whatever happens."""
        try:
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                for future in [pool.submit(self.ensure, job) for job in self.jobs]:
                    future.result()
            self.state["status"] = "done"
        except BlockedError as error:
            self.state |= {"status": "blocked", "blocked_reason": str(error)[-600:]}
        finally:
            self.state["finished"] = time.time()
            self.write_summary()

    def write_summary(self) -> None:
        """Atomic rewrite: state, setting, per-arm totals and per-task counts (no task text)."""
        ids = list(dict.fromkeys(job.instance_id for job in self.jobs))
        arms = sorted({str(job.slot.arm) for job in self.jobs})
        keys = {job_key(job, self.setting) for job in self.jobs}
        mine = [rec for rec in self.records if record_key(rec) in keys]
        out = {
            **self.state,
            "setting": {"reasoning": self.setting.reasoning, "step_limit": self.setting.step_limit},
            "jobs": len(self.jobs),
            "arms": {arm: arm_totals(mine, arm) for arm in arms},
            "tasks": per_task(mine, ids),
        }
        tmp = self.summary_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, indent=1))
        tmp.replace(self.summary_path)
