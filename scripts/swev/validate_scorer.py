"""Validate the Django scorer and the history scrub on the pilot tasks before any Glimmer run.

Per task: the gold patch must resolve, no patch must not, and the scrub must leave no commit
past HEAD. One task at a time (light desktop load); counts only; exit 1 on any failure.
Usage: python validate_scorer.py <django_rows.json> <instance_id>...
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from swev_env import HISTORY_COUNTS, Outcome, grade, scrub_history_script
from taskenv import Container

EXPECTED = {"gold": Outcome.RESOLVED, "none": Outcome.UNRESOLVED}


def history_check(image: str) -> dict:
    """History counts in the stock image, then after the scrub; ok when no future commit stays."""
    box = Container(image)  # network none, as the agent's container
    try:
        before = box.sh(HISTORY_COUNTS)[1].strip()
        started = time.time()
        box.sh(scrub_history_script(), timeout=900)
        scrub_s = round(time.time() - started, 1)
        after = box.sh(HISTORY_COUNTS)[1].strip()
    finally:
        box.stop()
    return {"before": before, "after": after, "scrub_s": scrub_s, "ok": after.endswith("future=0")}


def grade_check(row: dict, label: str) -> dict:
    """Grade the gold patch or no patch; ok when the outcome is the expected one."""
    started = time.time()
    found = grade(row, row["patch"] if label == "gold" else "")
    return {
        "patch": label,
        "outcome": str(found.outcome),
        "f2p": list(found.f2p),
        "p2p": list(found.p2p),
        "grade_s": round(time.time() - started, 1),
        "ok": found.outcome is EXPECTED[label],
    }


def main(rows_path: Path, ids: list[str]) -> int:
    rows = {row["instance_id"]: row for row in json.loads(rows_path.read_text())}
    ok = True
    for iid in ids:
        row = rows[iid]
        checks = [{"check": "history", **history_check(row["image"])}]
        checks += [{"check": "grade", **grade_check(row, label)} for label in EXPECTED]
        for check in checks:
            ok &= check["ok"]
            print(json.dumps({"id": iid, **check}), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2:]))
