"""Route B's train step on the training host: rows to adapter to installed name, plain kept plain.

Reuses the nightly job's host half (`ops/routeb_nightly_host.sh` via `nightly_host.TrainingHost`):
train inside `ops/gpu_run.sh`, install the round's name, verify, restore the last good preset if
verify fails. Any failed step raises after recovery; rows are deleted locally and on the host.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from training_plan import TrainingPlan


@dataclass(frozen=True)
class TrainJob:
    """One round's training: the plan, the names it installs under, and the verify inputs."""

    plan: TrainingPlan
    model: str  # Muse-Glimmer-30B-<domain>-r<N>
    adapter_set: str  # <domain>-r<N>: the GGUF is glimmer-<adapter_set>.gguf
    system: str
    questions: Sequence[dict[str, str]]
    lesson_ids: frozenset[str]


class HostLike(Protocol):
    """The two calls of nightly_host.TrainingHost the trainer uses."""

    def step(self, name: str, *args: str) -> None:
        """Run one host step; raises HostStepError."""
        ...

    def upload(self, files: Sequence[Path], host_dir: str) -> None:
        """Copy files into a host directory."""
        ...


@dataclass
class HostTrainer:
    """The real train step on the training host; rows are deleted locally and remotely after."""

    host: HostLike
    local_root: Path
    host_root: str
    say: Callable[[str], None] = print

    def train_and_install(self, job: TrainJob) -> str:
        """Write, upload, train, install, verify; clean the row files however it ends."""
        local = self._write(job)
        host_work = f"{self.host_root}/{job.adapter_set}"
        try:
            self.host.upload(
                [local / "train", local / "questions.jsonl", local / "system.txt"], host_work
            )
            self._cycle(job, host_work)
        finally:
            shutil.rmtree(local, ignore_errors=False)
            self.host.step("clean", host_work)
        return f"{host_work}/adapters/{job.adapter_set}"

    def _write(self, job: TrainJob) -> Path:
        local = self.local_root / job.adapter_set
        rows = local / "train" / job.adapter_set
        rows.mkdir(parents=True, mode=0o700)
        lines = [json.dumps({"messages": list(row.messages)}) for row in job.plan.rows]
        (rows / "train.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        questions = "".join(json.dumps(q) + "\n" for q in job.questions)
        (local / "questions.jsonl").write_text(questions, encoding="utf-8")
        (local / "system.txt").write_text(job.system, encoding="utf-8")
        return local

    def _cycle(self, job: TrainJob, host_work: str) -> None:
        """Train and install (ensure-up on failure), then verify (restore on failure)."""
        start = [job.plan.start_from] if job.plan.start_from else []
        self.say(f"train {job.adapter_set}: {len(job.plan.rows)} rows, start {start or 'plain'}")
        try:
            self.host.step("train", host_work, job.adapter_set, *start)
            self.host.step("install", job.model, job.adapter_set)
        except Exception as failed:
            _recover(self.host, "ensure-up", failed)
            raise
        try:
            self.host.step("verify", host_work, job.model, job.adapter_set)
        except Exception as failed:
            _recover(self.host, "restore", failed)
            raise


def _recover(host: HostLike, step: str, failed: Exception) -> None:
    """Run the recovery step unless the host already said Glimmer cannot be brought back."""
    if not getattr(failed, "glimmer_down", False):
        host.step(step)
