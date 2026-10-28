"""Add `subsystem` and `size_band` to an existing pool.json offline, without rebuilding it.

Usage: python label_pool.py <workdir>
"""

import json
import sys
from pathlib import Path

from strata import size_band, subsystem_of


def label_pool(pool: list[dict], patches: dict[str, str]) -> list[dict]:
    """Pool entries with the two strata fields added; raises KeyError for an id with no patch."""
    return [
        entry
        | {
            "subsystem": subsystem_of(patches[entry["instance_id"]]),
            "size_band": size_band(entry["gold_changed_lines"]),
        }
        for entry in pool
    ]


def main(workdir: Path) -> None:
    data = workdir / "data"
    rows = json.loads((data / "sqlglot_rows.json").read_text())
    patches = {row["instance_id"]: row["patch"] for row in rows}
    summary = json.loads((data / "pool.json").read_text())
    try:
        summary["pool"] = label_pool(summary["pool"], patches)
    except KeyError as err:
        raise SystemExit(f"pool entry {err} has no row in sqlglot_rows.json") from err
    (data / "pool.json").write_text(json.dumps(summary, indent=1))
    counts: dict[str, int] = {}
    for entry in summary["pool"]:
        counts[entry["subsystem"]] = counts.get(entry["subsystem"], 0) + 1
    print(f"labeled {len(summary['pool'])} pool entries: {counts}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
