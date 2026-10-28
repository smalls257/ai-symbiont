"""Choose the lessons a personal adapter trains on: repo filter, hold-out, gold-line leak check.

Repos are named explicitly (--repo, repeatable) and every lesson must carry its repo tag. A
lesson from outside phase 1 raises HoldOutViolationError; one quoting a phase-2 gold line is
dropped and named. Prints counts and ids only.
Usage: python select_lessons.py LESSONS ROWS TASKS OUT --repo django/django [--repo ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from swev_tasks import HISTORY, LATER

MIN_LEAK_CHARS = 20  # shorter gold lines ("return None", "})") are common code, not the answer


class HoldOutViolationError(ValueError):
    """A lesson comes from a task outside phase 1."""


def gold_lines(patch: str) -> set[str]:
    """Distinctive added or removed lines of a gold patch, stripped."""
    found = set()
    for line in patch.splitlines():
        if line[:1] not in "+-" or line.startswith(("+++", "---")):
            continue
        text = line[1:].strip()
        if len(text) >= MIN_LEAK_CHARS and any(ch.isalpha() for ch in text):
            found.add(text)
    return found


def strings_in(node: object) -> list[str]:
    """Every string value inside a lesson, however nested."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in strings_in(value)]
    if isinstance(node, list | tuple):
        return [s for value in node for s in strings_in(value)]
    return []


def leaks(lesson: dict, lines: set[str]) -> bool:
    """True when any string of the lesson contains a distinctive scored gold line."""
    return any(line in text for text in strings_in(lesson) for line in lines)


def check_hold_out(lesson: dict, history: set[str], later: set[str]) -> None:
    """Raise unless the lesson's source task (if it names one) is a phase-1 task."""
    source = lesson.get("instance_id")
    if source is None:
        return
    if source in later or source not in history:
        raise HoldOutViolationError(f"lesson {lesson.get('lesson_id')} comes from {source}")


def phase_sets(tasks: dict) -> tuple[set[str], set[str]]:
    """(phase-1 ids, phase-2 ids) of the task list."""
    history = {t["instance_id"] for t in tasks["tasks"] if t["phase"] == HISTORY}
    return history, {t["instance_id"] for t in tasks["tasks"] if t["phase"] == LATER}


def scored_gold_lines(rows: list[dict], later: set[str]) -> set[str]:
    """Distinctive gold lines of every phase-2 task."""
    return set().union(*(gold_lines(row["patch"]) for row in rows if row["instance_id"] in later))


def require_repo_tags(lessons: list[dict]) -> None:
    """Raise when a lesson has no repo tag: the filter could not place it."""
    untagged = [lesson.get("lesson_id") for lesson in lessons if not lesson.get("repo")]
    if untagged:
        raise ValueError(f"{len(untagged)} lessons have no repo tag, e.g. {untagged[:3]}")


def select(
    lessons: list[dict], repos: set[str], tasks: dict, rows: list[dict]
) -> tuple[list, dict]:
    """(kept lessons, counts): repo filter, hold-out check, leak drop."""
    require_repo_tags(lessons)
    history, later = phase_sets(tasks)
    scored = scored_gold_lines(rows, later)
    in_repo = [lesson for lesson in lessons if lesson["repo"] in repos]
    for lesson in in_repo:
        check_hold_out(lesson, history, later)
    leaking = [leaks(lesson, scored) for lesson in in_repo]
    kept = [lesson for lesson, bad in zip(in_repo, leaking, strict=True) if not bad]
    leaked = [lesson.get("lesson_id") for lesson, bad in zip(in_repo, leaking, strict=True) if bad]
    counts = {"read": len(lessons), "in_repos": len(in_repo), "dropped_leak": leaked}
    return kept, counts | {"kept": len(kept), "repos": sorted(repos)}


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="lesson selection for a personal adapter")
    for name in ("lessons", "rows", "tasks", "out"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--repo", action="append", required=True, help="repeat for several")
    args = parser.parse_args(argv)
    lessons = [json.loads(line) for line in args.lessons.read_text().splitlines() if line]
    tasks = json.loads(args.tasks.read_text())
    kept, counts = select(lessons, set(args.repo), tasks, json.loads(args.rows.read_text()))
    args.out.write_text("".join(json.dumps(lesson) + "\n" for lesson in kept))
    print(json.dumps(counts))


if __name__ == "__main__":
    main(sys.argv[1:])
