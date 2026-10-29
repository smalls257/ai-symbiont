"""Keep the PLUG-AGENT-1 tasks a grader can judge: an image, gold resolves, an empty patch fails.

Every dropped instance is listed with its reason; nothing is dropped silently. Runs on the desktop
(docker, network off inside the containers). Output holds ids, reasons and counts only.
Usage: python plug_agent_tasks.py <rows.json> <out.json> [workers]
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calibration"))

from taskenv import TaskEnvError, grade  # noqa: E402

WORKERS = 2  # light desktop load beside other runs


class Drop(StrEnum):
    """Why an instance cannot be a task."""

    NO_IMAGE = "no SWE-rebench image"
    GOLD_FAILS = "gold patch does not resolve"
    EMPTY_PASSES = "empty patch already resolves"
    NOT_GRADEABLE = "grader error"


def check(row: dict) -> tuple[str, str | None]:
    """(instance id, None if kept else the drop reason)."""
    if not row.get("docker_image"):
        return row["instance_id"], str(Drop.NO_IMAGE)
    try:
        if not grade(row["docker_image"], row, row["patch"], prepare=False).resolved:
            return row["instance_id"], str(Drop.GOLD_FAILS)
        if grade(row["docker_image"], row, "", prepare=False).resolved:
            return row["instance_id"], str(Drop.EMPTY_PASSES)
    except TaskEnvError as error:
        return row["instance_id"], f"{Drop.NOT_GRADEABLE}: {str(error)[:80]}"
    return row["instance_id"], None


def main() -> None:
    rows = json.loads(Path(sys.argv[1]).read_text())
    for row in rows:
        if isinstance(row.get("install_config"), str):
            row["install_config"] = json.loads(row["install_config"])
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else WORKERS
    with ThreadPoolExecutor(workers) as pool:
        verdicts = dict(pool.map(check, rows))
    kept = sorted(task for task, reason in verdicts.items() if reason is None)
    dropped = {task: reason for task, reason in sorted(verdicts.items()) if reason}
    document = {
        "kept": kept,
        "dropped": dropped,
        "counts": {"listed": len(rows), "kept": len(kept)},
    }
    Path(sys.argv[2]).write_text(json.dumps(document, indent=1))
    print(json.dumps(document["counts"]))


if __name__ == "__main__":
    main()
