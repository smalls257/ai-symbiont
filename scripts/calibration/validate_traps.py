"""Prove each constructed demo trap task is solvable and that its trap bites, before Glimmer runs.

Fresh container of the task image per check: no patch must not resolve, the gold patch must; a
naive_patch must apply and not resolve; a naive_command (gold fix applied, agent's 60 s timeout)
must fail while the lesson_command passes. A readiness check, never a benchmark result.

Usage: python validate_traps.py <rows.json> <out.json>   (next to taskenv.py)
"""

from __future__ import annotations

import json
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from taskenv import Container, apply_cmd, grade, write_file_cmd

AGENT_COMMAND_TIMEOUT_S = 60  # run_calibration's DockerEnvironment timeout for one agent command
TIMED_OUT_RC = 124  # coreutils `timeout`


def run_with_gold(row: dict, command: str) -> dict:
    """Run one shell command at /testbed with the gold fix applied, under the agent's timeout."""
    box = Container(row["image"])
    try:
        box.sh(write_file_cmd("/tmp/gold.patch", row["patch"]))
        box.sh(apply_cmd("/tmp/gold.patch"))
        started = time.monotonic()
        rc, out = box.sh(
            f"cd /testbed && timeout {AGENT_COMMAND_TIMEOUT_S} bash -c {shlex.quote(command)}",
            timeout=AGENT_COMMAND_TIMEOUT_S + 60,
            check=False,
        )
        last = out.strip().splitlines()[-1:] or [""]
        return {
            "command": command,
            "rc": rc,
            "timed_out": rc == TIMED_OUT_RC,
            "seconds": round(time.monotonic() - started, 1),
            "last_line": last[0][-160:],
        }
    finally:
        box.stop()


def naive_verdict(row: dict) -> dict:
    """Whether the trap bites: the naive edit fails grading, or the naive command fails."""
    if "naive_patch" in row:
        graded = grade(row["image"], row, row["naive_patch"], prepare=False)
        return {
            "kind": "patch",
            "patch_applied": graded.patch_applied,
            "f2p": [graded.f2p_passed, graded.f2p_total],
            "p2p": [graded.p2p_passed, graded.p2p_total],
            "bites": graded.patch_applied and not graded.resolved,
        }
    naive = run_with_gold(row, row["naive_command"])
    lesson = run_with_gold(row, row["lesson_command"])
    bites = naive["rc"] != 0 and lesson["rc"] == 0
    return {"kind": "command", "naive": naive, "lesson": lesson, "bites": bites}


def validate(row: dict) -> dict:
    """Base, gold and naive checks for one task row."""
    base = grade(row["image"], row, "", prepare=False)
    gold = grade(row["image"], row, row["patch"], prepare=False)
    naive = naive_verdict(row)
    return {
        "instance_id": row["instance_id"],
        "label": row["label"],
        "image": row["image"],
        "base_resolved": base.resolved,
        "base_f2p": [base.f2p_passed, base.f2p_total],
        "gold_resolved": gold.resolved,
        "gold_f2p_p2p": [gold.f2p_passed, gold.f2p_total, gold.p2p_passed, gold.p2p_total],
        "naive": naive,
        "valid": gold.resolved and not base.resolved and naive["bites"],
    }


if __name__ == "__main__":
    rows_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    task_rows = json.loads(rows_path.read_text())
    with ThreadPoolExecutor(len(task_rows)) as pool:
        results = list(pool.map(validate, task_rows))
    out_path.write_text(json.dumps(results, indent=1))
    for result in results:
        print(json.dumps(result))
    print(f"valid {sum(r['valid'] for r in results)}/{len(results)} -> {out_path}")
