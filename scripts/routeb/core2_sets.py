"""Core D2 task pools: per repository, EARLIER tasks (teacher training) and LATER candidates (test).

Per repository the imaged SWE-rebench tasks are split by date: the first EARLIER_SHARE are
earlier, the rest later. A later task is a test candidate only if its gold patch touches a
source file some earlier task of the same repository also touched (the fix-area match). Rows
stay local; the summary holds ids and counts. Needs duckdb and network.
Usage: python core2_sets.py --repos R [R ...] --out DIR
"""

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

import duckdb

SOURCE = "hf://datasets/nebius/SWE-rebench@~parquet/default/filtered/*.parquet"
EARLIER_SHARE = 0.55  # owner: earlier tasks train, later tasks test
COLUMNS = (
    "instance_id, repo, base_commit, created_at, patch, test_patch, problem_statement, "
    "install_config, FAIL_TO_PASS, PASS_TO_PASS, docker_image"
)
FILE = re.compile(r"^diff --git a/(\S+) b/")


def gold_files(patch: str) -> set[str]:
    """Source files a patch changes (test files excluded)."""
    found = {match.group(1) for match in map(FILE.match, patch.splitlines()) if match}
    return {path for path in found if "test" not in path.lower()}


def split_repo(rows: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """(earlier, later candidates) of one repository by date and fix-area match."""
    ordered = sorted(rows, key=lambda row: (str(row["created_at"]), row["instance_id"]))
    cut = int(len(ordered) * EARLIER_SHARE)
    earlier, later = ordered[:cut], ordered[cut:]
    seen = set().union(*(gold_files(row["patch"]) for row in earlier)) if earlier else set()
    return earlier, [row for row in later if gold_files(row["patch"]) & seen]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repos", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    marks = ", ".join("?" for _ in args.repos)
    query = f"SELECT {COLUMNS} FROM '{SOURCE}' WHERE docker_image IS NOT NULL AND repo IN ({marks})"  # noqa: S608 bound
    cursor = con.execute(query, args.repos)
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for repo in args.repos:
        earlier, later = split_repo([row for row in rows if row["repo"] == repo])
        name = repo.replace("/", "__")
        (args.out / f"{name}-earlier.json").write_text(json.dumps(earlier, default=str))
        (args.out / f"{name}-later.json").write_text(json.dumps(later, default=str))
        summary[repo] = {"earlier": len(earlier), "later_candidates": len(later)}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
