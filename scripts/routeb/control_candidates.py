"""Pick the control adapter's teacher tasks: SWE-rebench tasks from OTHER repositories.

One task per repository, with an image and a small gold patch, from repositories that are not
sqlglot, not Django and not any Plug repo (so no test task and no downstream-test task can be
among them), in a seeded order. Rows stay local; the run reads them. Needs duckdb and network.
Usage: python control_candidates.py --exclude-plan plan.json --count N --out rows.json
"""

import argparse
import json
import random
from pathlib import Path

import duckdb

SOURCE = "hf://datasets/nebius/SWE-rebench@~parquet/default/filtered/*.parquet"
CORE_REPOS = (  # Core D2 repositories: never in the control set
    "tobymao/sqlglot",
    "django/django",
    "streamlink/streamlink",
    "conan-io/conan",
    "iterative/dvc",
    "PennyLaneAI/pennylane",
)
MAX_GOLD_LINES = 15  # small fixes, like the Core earlier tasks (median gold patch of 2-8 lines)
SEED = 20261029
COLUMNS = (
    "instance_id, repo, base_commit, created_at, patch, test_patch, problem_statement, "
    "install_config, FAIL_TO_PASS, PASS_TO_PASS, docker_image"
)


def changed_lines(patch: str) -> int:
    """Added plus removed lines, file headers excluded."""
    return sum(
        1 for line in patch.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )


def one_per_repo(rows: list[dict], excluded: set[str], count: int) -> list[dict]:
    """The smallest-patch task of each allowed repository, `count` of them in a seeded order."""
    best: dict[str, dict] = {}
    for row in rows:
        size = changed_lines(row["patch"])
        if row["repo"] in excluded or not row["docker_image"] or size > MAX_GOLD_LINES:
            continue
        held = best.get(row["repo"])
        if held is None or (size, row["instance_id"]) < (
            changed_lines(held["patch"]),
            held["instance_id"],
        ):
            best[row["repo"]] = row
    picked = sorted(best.values(), key=lambda row: row["instance_id"])
    random.Random(SEED).shuffle(picked)
    return picked[:count]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exclude-plan", type=Path, required=True, help="Plug plan.json")
    parser.add_argument("--count", type=int, default=80)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.exclude_plan.read_text())
    excluded = (
        set(CORE_REPOS)
        | set(plan["validation"])
        | set(plan["scored"])
        | set(plan.get("meta_join", []))
    )
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    cursor = con.execute(f"SELECT {COLUMNS} FROM '{SOURCE}' WHERE docker_image IS NOT NULL")  # noqa: S608 constant
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]
    picked = one_per_repo(rows, excluded, args.count)
    args.out.write_text(json.dumps(picked, default=str))
    print(json.dumps({"rows_with_image": len(rows), "picked": len(picked)}))


if __name__ == "__main__":
    main()
