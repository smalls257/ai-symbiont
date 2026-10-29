"""Rows for the constructed demo trap tasks (demo_tasks/trap_tasks.toml), in calibration shape.

A row has what taskenv.grade and run_calibration's agent read, plus the task's own `image`, the
gold `patch`, one naive action (`naive_patch` or `naive_command`) and the note's `lesson`. A task
missing any of them raises TrapTaskError naming it, so an ungradable row never reaches a run.

Usage: python trap_rows.py <trap_tasks.toml> <rows.json>
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

LABEL = "constructed demo task"
REQUIRED = (
    "instance_id",
    "patch_dir",
    "image",
    "trap",
    "drop_paths",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "lesson",
)
LESSON_PARTS = ("happened", "resolved", "check")


class TrapTaskError(ValueError):
    """A trap task definition the runner could not grade."""


def _require(task: dict) -> None:
    name = task.get("instance_id", "<no instance_id>")
    missing = [key for key in REQUIRED if not task.get(key)]
    missing += [f"lesson.{part}" for part in LESSON_PARTS if not task.get("lesson", {}).get(part)]
    if missing:
        raise TrapTaskError(f"{name}: missing {', '.join(missing)}")


def _naive_action(task: dict, folder: Path) -> dict:
    """The naive move the trap punishes: an edit (naive.patch) or a command, never both."""
    name = task["instance_id"]
    naive_file = folder / "naive.patch"
    command = task.get("naive_command")
    if naive_file.exists() == bool(command):
        raise TrapTaskError(f"{name}: needs exactly one of naive.patch and naive_command")
    if not command:
        return {"naive_patch": naive_file.read_text()}
    if not task.get("lesson_command"):
        raise TrapTaskError(f"{name}: naive_command needs a lesson_command")
    return {"naive_command": command, "lesson_command": task["lesson_command"]}


def _read_patch(folder: Path, name: str, instance_id: str) -> str:
    path = folder / name
    if not path.is_file() or not path.read_text().strip():
        raise TrapTaskError(f"{instance_id}: {path} is missing or empty")
    return path.read_text()


def trap_row(task: dict, spec: dict, root: Path) -> dict:
    """One calibration-shaped row for a task of trap_tasks.toml; raises TrapTaskError."""
    _require(task)
    folder = root / task["patch_dir"]
    name = task["instance_id"]
    return {
        "instance_id": name,
        "label": LABEL,
        "image": task["image"],
        "trap": task["trap"],
        "drop_paths": list(task["drop_paths"]),
        "problem_statement": task["problem_statement"].strip() + "\n",
        "FAIL_TO_PASS": list(task["FAIL_TO_PASS"]),
        "PASS_TO_PASS": list(task["PASS_TO_PASS"]),
        "patch": _read_patch(folder, "gold.patch", name),
        "test_patch": _read_patch(folder, "hidden_test.patch", name),
        "install_config": {"test_cmd": task.get("test_cmd", spec["test_cmd"])},
        "lesson": {part: task["lesson"][part] for part in LESSON_PARTS},
        **_naive_action(task, folder),
    }


def load_trap_rows(tasks_file: Path) -> list[dict]:
    """Every task of a trap_tasks.toml as a row; patch_dir is relative to the file's folder.

    Raises TrapTaskError if the file is not labeled a constructed demo task or a task is incomplete.
    """
    spec = tomllib.loads(tasks_file.read_text())
    if spec.get("label") != LABEL:
        raise TrapTaskError(f"{tasks_file}: label must be {LABEL!r}")
    if not spec.get("task"):
        raise TrapTaskError(f"{tasks_file}: no [[task]] entries")
    return [trap_row(task, spec, tasks_file.parent) for task in spec["task"]]


if __name__ == "__main__":
    tasks_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    trap_rows = load_trap_rows(tasks_path)
    out_path.write_text(json.dumps(trap_rows, indent=1))
    print(f"{len(trap_rows)} rows ({LABEL}) -> {out_path}")
