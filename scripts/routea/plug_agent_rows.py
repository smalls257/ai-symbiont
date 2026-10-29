"""Fetch the SWE-rebench task rows of the PLUG-AGENT-1 instances (public data, kept local).

Runs where duckdb and the network are available (the desktop). Every listed id must come back
exactly once, or the script raises naming the missing ids; rows are never committed.
Usage: python plug_agent_rows.py [--dates] <ids.txt> <out.json>
"""

import json
import sys
from pathlib import Path

import duckdb

# the test split holds all 51 PLUG-AGENT-1 instances; the filtered split holds 34 of them
SOURCE = "hf://datasets/nebius/SWE-rebench@~parquet/default/test/*.parquet"
COLUMNS = (
    "instance_id, repo, base_commit, created_at, patch, test_patch, problem_statement, "
    "install_config, FAIL_TO_PASS, PASS_TO_PASS, docker_image"
)


def fetch(ids: list[str]) -> list[dict]:
    """The rows of `ids`; raises LookupError naming any id the dataset does not hold."""
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    marks = ", ".join("?" for _ in ids)
    query = f"SELECT {COLUMNS} FROM '{SOURCE}' WHERE instance_id IN ({marks})"  # noqa: S608 ids are bound
    cursor = con.execute(query, ids)
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]
    missing = sorted(set(ids) - {row["instance_id"] for row in rows})
    if missing or len(rows) != len(ids):
        raise LookupError(f"{len(missing)} ids not in SWE-rebench: {missing[:10]}")
    return rows


def fetch_dates(ids: list[str]) -> dict[str, str | None]:
    """`created_at` of each id; an id the dataset lacks maps to None (undated: excluded later)."""
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    marks = ", ".join("?" for _ in ids)
    query = f"SELECT instance_id, created_at FROM '{SOURCE}' WHERE instance_id IN ({marks})"  # noqa: S608 ids are bound
    found = {iid: str(created) for iid, created in con.execute(query, ids).fetchall()}
    return {iid: found.get(iid) for iid in ids}


def main() -> None:
    """`ROWS` mode writes full rows (must all exist); `--dates` writes id to created_at."""
    dates = sys.argv[1] == "--dates"
    paths = sys.argv[2:] if dates else sys.argv[1:]
    ids = [line.strip() for line in Path(paths[0]).read_text().splitlines() if line.strip()]
    found = fetch_dates(ids) if dates else fetch(ids)
    Path(paths[1]).write_text(json.dumps(found, default=str))
    print(f"{len(found)} {'dates' if dates else 'rows'}")


if __name__ == "__main__":
    main()
