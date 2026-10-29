"""Fetch SWE-bench Verified's Django rows and write the two-phase task list (desktop, network).

Writes <workdir>/data/django_rows.json (full rows, stays on the desktop) and
<workdir>/data/swev-django-tasks.json (ids, dates, sizes, labels: copied to results/).
Usage: python fetch_django_tasks.py <workdir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
from swev_tasks import EXCLUDED, HISTORY, LATER, REPO, candidates, kept, pilot_ids, select_phases

SOURCE = "hf://datasets/SWE-bench/SWE-bench_Verified/**/*.parquet"
COLUMNS = (
    "instance_id",
    "repo",
    "base_commit",
    "created_at",
    "version",
    "difficulty",
    "patch",
    "test_patch",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "environment_setup_commit",
    "image",
    "eval_script",
    "log_parser",
    "eval_type",
)


def django_rows() -> list[dict]:
    """Every Django row of the source, in date order."""
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    found = con.sql(
        f"SELECT {', '.join(COLUMNS)} FROM read_parquet('{SOURCE}') "
        f"WHERE repo = '{REPO}' ORDER BY created_at, instance_id"
    ).fetchall()
    return [dict(zip(COLUMNS, row, strict=True)) for row in found]


def task_list(rows: list[dict]) -> dict:
    """The committed task list: the rule, the counts and one entry per picked task."""
    entries = candidates(select_phases(rows))
    by_phase = {phase: [e for e in entries if e["phase"] == phase] for phase in (HISTORY, LATER)}
    return {
        "source": SOURCE,
        "repo": REPO,
        "rule": "date order by created_at; difficulty <15 min or 15 min-1 hour; "
        "ungradeable tasks excluded (no-patch pass or gold fail); "
        "history = earliest 20 kept, later = next 20",
        "excluded": sorted(EXCLUDED),
        "rows_for_repo": len(rows),
        "rows_kept": sum(map(kept, rows)),
        "counts": {phase: len(items) for phase, items in by_phase.items()},
        "date_range": {
            phase: [items[0]["created_at"], items[-1]["created_at"]]
            for phase, items in by_phase.items()
        },
        "pilot_ids": pilot_ids(entries),
        "tasks": entries,
    }


def main(workdir: Path) -> None:
    rows = django_rows()
    data = workdir / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "django_rows.json").write_text(json.dumps(rows, default=str))
    listed = task_list(rows)
    (data / "swev-django-tasks.json").write_text(json.dumps(listed, indent=1))
    print(json.dumps({key: listed[key] for key in ("rows_for_repo", "rows_kept", "counts")}))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
