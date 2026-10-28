"""Pick the SWE-bench Verified Django tasks for the headline run: date order, two phases.

The split is by created_at only, so every lesson's task precedes every scored task. Hard
difficulty labels and tasks the hidden tests cannot grade are dropped; a short list raises.
"""

from __future__ import annotations

import json

REPO = "django/django"
HISTORY_N = 20  # dispatch: "the earliest ~20 tasks" give the lessons
LATER_N = 20  # dispatch: "the next ~20-30"; 20 keeps phase 2 at 80 runs (see swev-report.md)
PILOT_N = 3  # dispatch: images pulled and the scorer validated on 3 tasks first
KEPT_DIFFICULTIES = ("<15 min fix", "15 min - 1 hour")
HISTORY, LATER = "history", "later"
# Tasks that cannot tell a fix from no fix: the official FAIL_TO_PASS tests already pass on the
# untouched base tree in the official image, so any submitted patch "resolves". Found by
# validate_scorer.py (no-patch check); each entry names the measurement.
EXCLUDED = {
    "django__django-7530": "FAIL_TO_PASS passes with no patch (validate_scorer, 2026-10-28)",
}


class TaskSelectionError(ValueError):
    """The dataset cannot fill both phases under the rule; never return a short list quietly."""


def changed_lines(diff: str) -> int:
    """Added plus removed lines of a unified diff, file headers excluded."""
    return sum(
        1 for ln in diff.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))
    )


def listed_tests(field: str | list[str]) -> list[str]:
    """FAIL_TO_PASS / PASS_TO_PASS as a list; the dataset ships them as JSON strings."""
    return json.loads(field) if isinstance(field, str) else list(field)


def kept(row: dict) -> bool:
    """A Django task with a kept difficulty label that the hidden tests can grade."""
    usable = row["instance_id"] not in EXCLUDED
    return usable and row["repo"] == REPO and row["difficulty"] in KEPT_DIFFICULTIES


def select_phases(rows: list[dict]) -> dict[str, list[dict]]:
    """{history: earliest HISTORY_N kept rows, later: the next LATER_N}, both in date order.

    Ties on created_at are broken by instance id so the split is reproducible. Raises
    TaskSelectionError when fewer than HISTORY_N + LATER_N rows are kept.
    """
    ordered = sorted(filter(kept, rows), key=lambda row: (row["created_at"], row["instance_id"]))
    need = HISTORY_N + LATER_N
    if len(ordered) < need:
        raise TaskSelectionError(f"{len(ordered)} kept {REPO} rows, the rule needs {need}")
    return {HISTORY: ordered[:HISTORY_N], LATER: ordered[HISTORY_N:need]}


def candidate_entry(row: dict, phase: str, order: int) -> dict:
    """One task's public metadata: ids, date, sizes and labels, never task text."""
    return {
        "instance_id": row["instance_id"],
        "phase": phase,
        "order": order,
        "created_at": row["created_at"],
        "version": row["version"],
        "difficulty": row["difficulty"],
        "gold_changed_lines": changed_lines(row["patch"]),
        "n_fail_to_pass": len(listed_tests(row["FAIL_TO_PASS"])),
        "n_pass_to_pass": len(listed_tests(row["PASS_TO_PASS"])),
        "docker_image": row["image"],
    }


def candidates(phases: dict[str, list[dict]]) -> list[dict]:
    """Every picked task in date order, numbered from 1 across both phases."""
    picked = [(phase, row) for phase in (HISTORY, LATER) for row in phases[phase]]
    return [candidate_entry(row, phase, order) for order, (phase, row) in enumerate(picked, 1)]


def pilot_ids(entries: list[dict]) -> list[str]:
    """The first PILOT_N history tasks: the scorer is validated on them before anything runs."""
    return [entry["instance_id"] for entry in entries if entry["phase"] == HISTORY][:PILOT_N]
