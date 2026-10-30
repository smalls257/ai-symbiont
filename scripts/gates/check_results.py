"""QG-SCI-03 row-role labels and the counters row. Prevents Silent Fallback by omission:
a fly that ties the counters cannot be hidden by leaving the baseline out of the table.

For every results/*.json that holds a scoreboard (a top-level "rows" list):
  * every row carries role in {floor, ceiling, reference, under_test} ("under test" is the
    dashboard's spelling and is accepted),
  * every fly (mushroom) row has a counters row for the same split.
Result files with no "rows" list (calibration summaries) are not scoreboards and are skipped.

Usage: check_results.py [FILE.json ...]   default: every results/*.json
"""

import json
import sys
from pathlib import Path

ROLES = {"floor", "ceiling", "reference", "under_test"}
FLY_ARMS = {"fly", "mushroom"}
COUNTERS_ARM = "counters"


def normalise_role(role: object) -> str:
    return str(role).strip().replace(" ", "_").lower()


def arm_of(row: dict) -> str:
    return str(row.get("arm", row.get("key", ""))).lower()


def _bad_roles(name: str, rows: list[dict]) -> list[str]:
    return [
        f"{name}: row '{arm_of(r) or '?'}' has role {r.get('role')!r}, not one of {sorted(ROLES)}"
        for r in rows
        if normalise_role(r.get("role")) not in ROLES
    ]


def _unpaired_fly_rows(name: str, rows: list[dict]) -> list[str]:
    counters_splits = {r.get("split") for r in rows if arm_of(r) == COUNTERS_ARM}
    return [
        f"{name}: fly row on split {r.get('split')!r} has no counters row beside it"
        for r in rows
        if arm_of(r) in FLY_ARMS and r.get("split") not in counters_splits
    ]


def problems_in(name: str, document: object) -> list[str]:
    if not isinstance(document, dict) or not isinstance(document.get("rows"), list):
        return []
    rows = [r for r in document["rows"] if isinstance(r, dict)]
    return _bad_roles(name, rows) + _unpaired_fly_rows(name, rows)


def main(argv: list[str], root: Path) -> int:
    files = [Path(a) for a in argv] or sorted((root / "results").glob("*.json"))
    problems = []
    for path in files:
        problems += problems_in(path.name, json.loads(path.read_text()))
    for line in problems:
        print(f"QG-SCI-03: {line}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], Path(__file__).resolve().parents[2]))
