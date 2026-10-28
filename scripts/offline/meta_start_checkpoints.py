"""Checkpoints of T39 meta-training jobs, so a lost machine costs one check, not the run.

Each job writes its progress after every validation check (`<key>.progress.json`) and its
result when it ends (`<key>.done.json`); both are written to a temporary name and renamed,
so a crash never leaves half a file. JSON floats round-trip exactly, so a resumed job ends
where an unbroken one would. Numbers only, under the gitignored data/ or run directories.
"""

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from symbiont.core.meta import MetaStart
from symbiont.eval.meta_start import Adam, MetaProgress


def write_atomically(path: Path, document: dict[str, Any]) -> None:
    """Write json to `path` through a temporary file and a rename."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document))
    os.replace(temporary, path)


def progress_document(progress: MetaProgress) -> dict[str, Any]:
    """The progress as plain json values."""
    return {
        "step": progress.step,
        "start": progress.start.as_vector().tolist(),
        "best": progress.best.as_vector().tolist(),
        "curve": [list(point) for point in progress.curve],
        "stale": progress.stale,
        "adam": {
            "rate": progress.adam.rate,
            "first": progress.adam.first.tolist(),
            "second": progress.adam.second.tolist(),
            "count": progress.adam.count,
        },
        "rng_state": progress.rng_state,
    }


def progress_of(document: dict[str, Any], template: MetaStart) -> MetaProgress:
    """The progress stored in `document`; `template` gives the start's shape."""
    adam = document["adam"]
    return MetaProgress(
        step=document["step"],
        start=template.with_vector(np.array(document["start"])),
        best=template.with_vector(np.array(document["best"])),
        curve=tuple((int(step), float(loss)) for step, loss in document["curve"]),
        stale=document["stale"],
        adam=Adam(adam["rate"], np.array(adam["first"]), np.array(adam["second"]), adam["count"]),
        rng_state=document["rng_state"],
    )


class JobCheckpoint:
    """The progress and done files of one job in a checkpoint directory."""

    def __init__(self, directory: str | Path, key: str) -> None:
        """Name the job's files; the directory is created if missing."""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.progress_path = root / f"{key}.progress.json"
        self.done_path = root / f"{key}.done.json"

    def save_progress(self, progress: MetaProgress) -> None:
        """Store the progress after a validation check."""
        write_atomically(self.progress_path, progress_document(progress))

    def resume_from(self, template: MetaStart) -> MetaProgress | None:
        """The last stored progress, or None for a job never checked."""
        if not self.progress_path.exists():
            return None
        return progress_of(json.loads(self.progress_path.read_text()), template)

    def save_done(self, result: dict[str, Any]) -> None:
        """Store the finished job (its start as a list)."""
        write_atomically(self.done_path, result)

    def done(self) -> dict[str, Any] | None:
        """The finished job, or None if it has not finished."""
        if not self.done_path.exists():
            return None
        found: dict[str, Any] = json.loads(self.done_path.read_text())
        return found
