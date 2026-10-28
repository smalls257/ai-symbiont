"""Check a training manifest against the hold-out: no held-out task may have trained a model.

Lessons are deleted after training; the manifest (`Store.forget_trained`) keeps their
ids, source sessions and task ids, so this check still runs after the text is gone.
"""

import json
from pathlib import Path

from symbiont.records.holdout import HoldOutViolationError, normalise_task_id


def check_manifest_against_hold_out(manifest_path: Path, held_out_tasks: frozenset[str]) -> int:
    """Return how many lessons the manifest lists; raise HoldOutViolationError on a held-out task.

    A manifest that is missing or not one written by the store raises (OSError,
    KeyError, ValueError): unreadable evidence is not evidence of a clean run.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    held = {normalise_task_id(t) for t in held_out_tasks}
    for lesson in manifest["lessons"]:
        for task_id in lesson["task_ids"]:
            if held and normalise_task_id(task_id) in held:
                raise HoldOutViolationError(task_id, lesson["session_id"])
    count = int(manifest["counts"]["lessons"])
    if count != len(manifest["lessons"]):
        raise ValueError(
            f"manifest {manifest_path} counts {count} lessons but lists {len(manifest['lessons'])}"
        )
    return count
