"""Keep the PLUG-AGENT-1 tasks a grader can judge: an image, gold resolves, an empty patch fails.

Every dropped instance is listed with its reason; nothing is dropped silently. Runs on the desktop
(docker, network off inside the containers). Output holds ids, reasons and counts only.
Usage: python plug_agent_tasks.py <rows.json> <out.json> [workers]
"""

import json
import subprocess
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
    TIMES_OUT = "tests time out (20 min)"


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
    except subprocess.TimeoutExpired:
        return row["instance_id"], str(Drop.TIMES_OUT)
    return row["instance_id"], None


def checked(rows: list[dict], log: Path, workers: int) -> dict[str, str | None]:
    """Verdicts, resumed from `log` (one JSON line per finished instance) and appended to it."""
    done: dict[str, str | None] = {}
    if log.is_file():
        for line in log.read_text().splitlines():
            if line:
                found = json.loads(line)
                done[found["id"]] = found["drop"]
    todo = [row for row in rows if row["instance_id"] not in done]
    with ThreadPoolExecutor(workers) as pool, log.open("a") as out:
        for task, reason in pool.map(check, todo):
            out.write(json.dumps({"id": task, "drop": reason}) + "\n")
            out.flush()
            done[task] = reason
    return done


def main() -> None:
    rows = json.loads(Path(sys.argv[1]).read_text())
    for row in rows:
        if isinstance(row.get("install_config"), str):
            row["install_config"] = json.loads(row["install_config"])
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else WORKERS
    verdicts = checked(rows, Path(sys.argv[2]).with_suffix(".progress.jsonl"), workers)
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
