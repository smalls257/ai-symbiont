"""Build one Docker image per constructed demo trap task (demo_tasks/Dockerfile).

Each image is the ledgerline repo minus the task's `drop_paths`, committed once at /testbed.
A failed build raises CalledProcessError with docker's own output: no image is half-built quietly.

Usage: python build_trap_images.py <rows.json> <ledgerline_dir> <Dockerfile>
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def build_command(row: dict, context: Path, dockerfile: Path) -> list[str]:
    """The docker build command line for one task row."""
    return [
        "docker", "build", "-q", "-f", str(dockerfile), "-t", row["image"],
        "--label", f"symbiont.label={row['label']}",
        "--label", f"symbiont.instance_id={row['instance_id']}",
        "--build-arg", f"DROP_PATHS={' '.join(row['drop_paths'])}", str(context),
    ]  # fmt: skip


if __name__ == "__main__":
    rows_path, context_dir, dockerfile_path = (Path(arg) for arg in sys.argv[1:4])
    for task_row in json.loads(rows_path.read_text()):
        subprocess.run(build_command(task_row, context_dir, dockerfile_path), check=True)
        print(f"built {task_row['image']} for {task_row['instance_id']}")
