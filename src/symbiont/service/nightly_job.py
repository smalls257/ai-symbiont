"""The state of a background nightly job: running, done with N lessons at T, or failed and why.

`symbiont nightly start` returns while the 1-4 minute training goes on in a detached process, so
the developer needs somewhere to ask. The job writes one small file per repository; `symbiont
status` reads it. A job killed from outside cannot write its own failure, so a "running" file that
began more than `STALE_AFTER_S` ago is reported as an interrupted job, never as still running.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

JOB_FILE = "job.json"
JOB_LOG = "job.log"
# Training is 1-4 minutes and the kit merge about one more [measured, README]; 3 h is far beyond
# any honest run, so a file older than that belongs to a job that was killed.
STALE_AFTER_S = 3 * 3600


class JobPhase(StrEnum):
    """Where the background job stands."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class JobState:
    """One job: its phase, when it began (ISO, UTC), the lessons it trains on and why it failed."""

    phase: JobPhase
    started: str
    lessons: int | None = None
    finished: str | None = None
    reason: str = ""


def utc_now() -> str:
    """Now as an ISO UTC string to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def job_path(nightly_dir: Path, project: str) -> Path:
    """Where the project's job file lives."""
    return nightly_dir / project / JOB_FILE


def write_job(nightly_dir: Path, project: str, state: JobState) -> None:
    """Write the state atomically, so a reader never sees half a file."""
    path = job_path(nightly_dir, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps(asdict(state), indent=1) + "\n", encoding="utf-8")
    os.replace(partial, path)


def read_job(nightly_dir: Path, project: str) -> JobState | None:
    """The state, or None when no job ever started. An unreadable file raises ValueError."""
    path = job_path(nightly_dir, project)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return JobState(JobPhase(raw["phase"]), raw["started"], raw.get("lessons"),
                        raw.get("finished"), raw.get("reason", ""))  # fmt: skip
    except (OSError, ValueError, KeyError, TypeError) as unusable:
        raise ValueError(f"the training job file {path} is unusable ({unusable})") from unusable


def job_sentence(nightly_dir: Path, project: str, now: datetime | None = None) -> str | None:
    """One sentence for `symbiont status`, or None when no job ever started."""
    try:
        state = read_job(nightly_dir, project)
    except ValueError as unusable:
        return f"training job: {unusable}"
    if state is None:
        return None
    counted = "" if state.lessons is None else f" on {state.lessons} lessons"
    if state.phase is JobPhase.DONE:
        return f"training job: done{counted} at {state.finished}"
    if state.phase is JobPhase.FAILED:
        return f"training job: failed at {state.finished}: {state.reason}"
    if _age_s(state.started, now or datetime.now(UTC)) > STALE_AFTER_S:
        return (
            f"training job: failed: started {state.started} and never finished, so it was "
            f"interrupted (log {nightly_dir / project / JOB_LOG}); run `/symbiont nightly` again"
        )
    log = nightly_dir / project / JOB_LOG
    return f"training job: running{counted} since {state.started} (log {log})"


def _age_s(started: str, now: datetime) -> float:
    """Seconds since `started`."""
    return (now - datetime.fromisoformat(started)).total_seconds()
