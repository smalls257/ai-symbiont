"""PLUG-AGENT-2 smoke driver: the none arm over the smoke tasks, two at a time, images just in time.

Each task runs in its own child (plug_agent2_smoke_one.py), which removes the task image when it
ends. Before a pull the driver reads the image's registry size and the free disk; a task whose
image is larger than IMAGE_LIMIT_GB, or a disk below DISK_FLOOR_GB, is recorded as skipped with
its reason and nothing is pulled. Resumes from runs.jsonl.
Usage: python plug_agent2_smoke.py <smoke-rows.json> <out-dir> [--workers 2]
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

IMAGE_LIMIT_GB = 8  # one SWE-rebench image is 1 to 5 GB; a larger one is skipped, not pulled
DISK_FLOOR_GB = 60  # the desktop's WSL disk is shared with Core's runs
GB = 1e9


def claimed(out: Path, task: str) -> bool:
    """True if this driver is the first to claim the task (two drivers, one per server, share
    the output directory)."""
    (out / "claims").mkdir(exist_ok=True)
    name = hashlib.sha256(task.encode()).hexdigest()[:24]
    try:
        handle = os.open(out / "claims" / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(handle, os.environ.get("PLUG2_SERVER", "laptop").encode())  # who holds the claim
        os.close(handle)
    except FileExistsError:
        return False
    return True


def registry_size_gb(image: str) -> float | None:
    """Compressed layer sizes from the registry manifest, or None when it cannot be read."""
    found = subprocess.run(
        ["docker", "manifest", "inspect", image], capture_output=True, text=True, check=False
    )
    if found.returncode:
        return None
    manifest = json.loads(found.stdout)
    layers = manifest.get("layers") or [
        layer for entry in manifest.get("manifests", [])[:1] for layer in [entry]
    ]
    return sum(layer.get("size", 0) for layer in layers) / GB


def refusal(row: dict, out: Path) -> str | None:
    """Why this task's image must not be pulled now, or None."""
    free = shutil.disk_usage(out).free / GB
    if free < DISK_FLOOR_GB:
        return f"disk free {free:.0f} GB below {DISK_FLOOR_GB}"
    size = registry_size_gb(row["docker_image"])
    if size is None:
        return "image size unreadable; not pulled"
    return f"image {size:.1f} GB over {IMAGE_LIMIT_GB}" if size > IMAGE_LIMIT_GB else None


def run_child(row: dict, rows_file: Path, out: Path) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).with_name("plug_agent2_smoke_one.py")),
        str(rows_file),
        row["instance_id"],
        str(out),
    ]
    child = subprocess.run(command, capture_output=True, text=True, check=False)
    lines = [line for line in child.stdout.splitlines() if line.startswith("{")]
    if lines:
        return json.loads(lines[-1])
    return {"instance_id": row["instance_id"], "error_kind": "infra", "error": child.stderr[-200:]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rows", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    log = args.out / "runs.jsonl"
    done = (
        {json.loads(x)["instance_id"] for x in log.read_text().splitlines()}
        if log.is_file()
        else set()
    )
    lock = threading.Lock()

    def work(row: dict) -> None:
        if not claimed(args.out, row["instance_id"]):
            return
        reason = refusal(row, args.out)
        record = (
            {"instance_id": row["instance_id"], "skipped": reason}
            if reason
            else run_child(row, args.rows, args.out)
        )
        with lock, log.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    todo = [row for row in json.loads(args.rows.read_text()) if row["instance_id"] not in done]
    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(work, todo))


if __name__ == "__main__":
    main()
