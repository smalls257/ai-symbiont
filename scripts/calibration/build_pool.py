"""Build the sqlglot calibration pool from nebius/SWE-rebench (v1, `filtered` split).

Runs on the desktop (needs duckdb + network). Writes:
  <workdir>/data/sqlglot_rows.json   full task rows (problem text, patches): stays on the
                                     desktop, never committed
  <workdir>/data/pool.json           pool ids + sizes (no task text)

Pool rule (plan Task 22): sqlglot rows that have a docker image and a gold patch under
MAX_GOLD_LINES changed lines. "Changed lines" = added + removed lines of the diff, headers excluded;
the raw diff length is recorded too so the cut can be re-argued without re-downloading.

Usage: python build_pool.py <workdir>
"""

import json
import sys
from pathlib import Path

import duckdb

SOURCE = "hf://datasets/nebius/SWE-rebench@~parquet/default/filtered/*.parquet"
REPO = "tobymao/sqlglot"
MAX_GOLD_LINES = 60  # plan Task 22: keeps Glimmer runs short at ~12 tok/s decode
COLUMNS = [
    "instance_id",
    "base_commit",
    "created_at",
    "patch",
    "test_patch",
    "problem_statement",
    "install_config",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "docker_image",
]


def changed_lines(diff: str) -> int:
    return sum(
        1 for ln in diff.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))
    )


def main(workdir: Path) -> None:
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    rows = con.sql(
        f"SELECT {', '.join(COLUMNS)} FROM read_parquet('{SOURCE}') "
        f"WHERE repo = '{REPO}' ORDER BY created_at"
    ).fetchall()
    rows = [dict(zip(COLUMNS, row, strict=True)) for row in rows]
    data = workdir / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "sqlglot_rows.json").write_text(json.dumps(rows, default=str))

    pool, excluded = [], {"no_image": 0, "too_big": 0}
    for row in rows:
        if not row["docker_image"]:
            excluded["no_image"] += 1
            continue
        size = changed_lines(row["patch"])
        if size >= MAX_GOLD_LINES:
            excluded["too_big"] += 1
            continue
        pool.append(
            {
                "instance_id": row["instance_id"],
                "gold_changed_lines": size,
                "gold_diff_lines": len(row["patch"].splitlines()),
                "n_fail_to_pass": len(row["FAIL_TO_PASS"] or []),
                "n_pass_to_pass": len(row["PASS_TO_PASS"] or []),
            }
        )
    summary = {
        "source": SOURCE,
        "repo": REPO,
        "rows_for_repo": len(rows),
        "rule": f"docker_image present and gold patch changed lines < {MAX_GOLD_LINES}",
        "excluded": excluded,
        "pool_size": len(pool),
        "pool": pool,
    }
    (data / "pool.json").write_text(json.dumps(summary, indent=1))
    print(f"rows={len(rows)} pool={len(pool)} excluded={excluded}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
