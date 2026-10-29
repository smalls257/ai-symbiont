"""Count the general-pilot runs per arm and per task kind (bug, feature), counts only.

Each arm's log is CAL2's calibration.jsonl; every record must carry the arm the driver stamped
and a task from the split, or the script raises, so a stray run is never counted.
Usage: uv run python scripts/routeb/score_general_pilot.py --split F --plain LOG --card LOG --out J
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

ARMS = {"plain": "plain", "card": "lesson"}  # pilot arm -> the driver's arm stamp
LABELS = {"plain": "reference: plain Glimmer", "card": "under test: plain Glimmer + general card"}


def _graded(path: Path, stamp: str, kinds: dict[str, str]) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    found = []
    for row in rows:
        if row.get("instance_id") not in kinds or row.get("arm") != stamp:
            raise ValueError(
                f"{path}: record {row.get('instance_id')} arm {row.get('arm')} is not {stamp}"
            )
        if row.get("resolved") is not None:
            found.append(row)
    return found


def _tally(rows: Sequence[dict]) -> dict[str, int]:
    sent = [row for row in rows if row.get("submitted")]
    return {
        "runs": len(rows),
        "solved": sum(bool(r["resolved"]) for r in rows),
        "submitted": len(sent),
    }


def score(split: dict, logs: dict[str, Path]) -> dict:
    """Solved and submitted runs per arm, overall and per kind."""
    kinds = {entry["task"]: entry["kind"] for entry in split["evaluation"]}
    arms = {}
    for arm, path in logs.items():
        rows = _graded(path, ARMS[arm], kinds)
        per_kind = {
            kind: _tally([r for r in rows if kinds[r["instance_id"]] == kind])
            for kind in ("bug", "feature")
        }
        arms[arm] = {"label": LABELS[arm], "all": _tally(rows), **per_kind}
    return {
        "label": "exploratory: general-lessons prompt pilot, 1 run per task per arm",
        "arms": arms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--split", "--plain", "--card", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    found = score(json.loads(args.split.read_text()), {"plain": args.plain, "card": args.card})
    args.out.write_text(json.dumps(found, indent=1) + "\n")
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
