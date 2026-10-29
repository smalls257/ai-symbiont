"""Glimmer calibration trajectories as mini-SWE-agent reader rows, and the gold-line guard.

The runs were saved in tool-call form; `reader_row` re-wraps each step as the reader's text chat
and changes no command or output. The guard refuses a history whose lessons quote a line of the
replayed task's gold patch: a note that knew the fix would be a leak, not a memory.
Usage: uv run python scripts/routea/replay_rows.py history|target|check-gold ... (see replay.sh)
"""

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from symbiont.miner.lessons import Lesson
from symbiont.store.local import Store

TRAJ_GLOB = "traj/*/*.traj.json"
# Short added lines (a bracket, `else:`) appear everywhere; only a line this long names the fix.
MIN_GOLD_CHARS = 12


class TrajectoryShapeError(ValueError):
    """A trajectory is not in the tool-call format; the message names the file and message."""


class GoldLineLeakError(RuntimeError):
    """A lesson quotes a line of the replayed task's gold patch; training must not start."""


def reader_row(trajectory: dict[str, Any], trajectory_id: str, instance_id: str) -> dict[str, Any]:
    """One reader row: the task, then each command as a bash block and its observation."""
    messages = []
    for index, message in enumerate(trajectory["messages"]):
        role = message.get("role")
        if role in ("system", "exit"):
            continue
        if role == "user":
            messages.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": _bash_block(message, index)})
        elif role == "tool":
            messages.append({"role": "user", "content": message["content"]})
        else:
            raise TrajectoryShapeError(f"{trajectory_id} message {index}: role {role!r}")
    return {"trajectory_id": trajectory_id, "instance_id": instance_id, "messages": messages}


def _bash_block(message: dict[str, Any], index: int) -> str:
    actions = message.get("extra", {}).get("actions", [])
    if len(actions) != 1:
        raise TrajectoryShapeError(f"message {index}: {len(actions)} actions, expected 1")
    return f"```bash\n{actions[0]['command']}\n```"


def trajectory_files(runs_dirs: Iterable[Path], exclude_task: str) -> list[Path]:
    """Every trajectory under the run directories except the excluded task's, in name order."""
    found = [path for runs in runs_dirs for path in sorted(runs.glob(TRAJ_GLOB))]
    return [path for path in found if path.parent.name != exclude_task]


def row_of_file(path: Path) -> dict[str, Any]:
    """The reader row of one saved trajectory, named `<runs dir>/<task>/<run>`."""
    task = path.parent.name
    run_id = f"{path.parents[2].name}/{task}/{path.name.removesuffix('.traj.json')}"
    return reader_row(json.loads(path.read_text(encoding="utf-8")), run_id, task)


def write_rows(paths: Sequence[Path], out: Path) -> int:
    """Write one reader row per trajectory; returns how many were written."""
    with out.open("w", encoding="utf-8") as fh:
        for path in paths:
            fh.write(json.dumps(row_of_file(path)) + "\n")
    return len(paths)


def gold_lines(patch: str) -> set[str]:
    """The lines a unified diff adds, stripped, that are long enough to name the fix."""
    added = (line[1:].strip() for line in patch.splitlines() if line.startswith("+"))
    return {line for line in added if len(line) >= MIN_GOLD_CHARS and not line.startswith("++")}


def lesson_texts(lesson: Lesson) -> list[str]:
    """Every piece of a lesson that could reach the memory model's training rows."""
    return [lesson.quote, *lesson.resolution, *lesson.changed_alongside]


def refuse_gold_leaks(lessons: Sequence[Lesson], gold: set[str]) -> int:
    """Raise GoldLineLeakError naming the count when any lesson quotes a gold line."""
    leaking = [
        lesson
        for lesson in lessons
        if any(line in text for text in lesson_texts(lesson) for line in gold)
    ]
    if leaking:
        raise GoldLineLeakError(f"{len(leaking)} lessons quote a gold line of the replayed task")
    return len(lessons)


def task_patch(rows_file: Path, task: str) -> str:
    """The gold patch of `task` from the SWE-bench rows file; raises KeyError when absent."""
    rows = json.loads(rows_file.read_text(encoding="utf-8"))
    found = [row["patch"] for row in rows if row["instance_id"] == task]
    if not found:
        raise KeyError(f"{task} is not in {rows_file}")
    return found[0]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    history = commands.add_parser("history")
    history.add_argument("--out", type=Path, required=True)
    history.add_argument("--exclude", required=True, help="the replayed task id")
    history.add_argument("runs", type=Path, nargs="+")
    target = commands.add_parser("target")
    target.add_argument("--out", type=Path, required=True)
    target.add_argument("trajectory", type=Path)
    gold = commands.add_parser("check-gold")
    gold.add_argument("--data-dir", type=Path, required=True)
    gold.add_argument("--project", required=True)
    gold.add_argument("--task", required=True)
    gold.add_argument("rows", type=Path, help="SWE-bench rows JSON with each task's patch")
    return parser


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    if args.command == "history":
        count = write_rows(trajectory_files(args.runs, args.exclude), args.out)
        print(f"history: {count} trajectories, {args.exclude} excluded")
    elif args.command == "target":
        print(f"target: {write_rows([args.trajectory], args.out)} trajectory")
    else:
        lessons = Store.open(args.data_dir / "store.db").lessons(args.project)
        gold = gold_lines(task_patch(args.rows, args.task))
        checked = refuse_gold_leaks(lessons, gold)
        print(f"gold guard: {checked} lessons, {len(gold)} gold lines, 0 quoted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
