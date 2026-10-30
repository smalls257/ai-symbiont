"""Plug round 4's long-history repositories: list them, then export at most 2 trajectories per task.

Usage: uv run python scripts/datasets/export_long_repos.py list --counts task-counts.json
Usage:   --pool-dir POOL --meta2-dir META2 --plan PLAN --out long-pool.json
Usage: uv run --with duckdb python scripts/datasets/export_long_repos.py export
Usage:   --list long-pool.json --out-dir DIR

`list` fixes the sets before any row is read. Scored candidates: repositories with at least
MIN_TASKS tasks that were never in the plug pool (meta2's earlier export marked). Validation: round
3's validation and scored repositories with at least VALIDATION_MIN_TASKS tasks, only the tasks
round 3's pool cap left out. Every task keeps PER_TASK trajectories, the lowest by sha256 of
`SEED:<trajectory_id>`, so a repository's history spans many tasks rather than a few.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from fresh_pool import repo_names  # noqa: E402

from symbiont.eval.repo_pool import EXCLUDED, HELD_OUT, UNREADABLE  # noqa: E402

MIN_TASKS = 15  # 10 nights plus later sessions to score
VALIDATION_MIN_TASKS = 10
PER_TASK = 2
SEED = "plug-r4"


def listed(counts: dict, pool: Path, meta2: Path, plan: dict) -> list[dict]:
    """The scored candidates and the validation repositories with the tasks each may export."""
    in_pool, read_by_meta2 = repo_names(pool), repo_names(meta2)
    blocked = set(HELD_OUT) | set(EXCLUDED) | set(UNREADABLE) | in_pool
    capped = pool_tasks(pool)
    found = [
        {
            "repo": repo,
            "set": "scored",
            "meta2_exported": repo in read_by_meta2,
            "tasks": sorted(tasks),
        }
        for repo, tasks in sorted(counts.items())
        if repo not in blocked and len(tasks) >= MIN_TASKS
    ]
    for repo in sorted(set(plan["validation"]) | set(plan["scored"])):
        if len(counts.get(repo, {})) >= VALIDATION_MIN_TASKS:
            beyond = sorted(set(counts[repo]) - capped.get(repo, set()))
            found.append(
                {"repo": repo, "set": "validation", "meta2_exported": False, "tasks": beyond}
            )
    return found


def rest(counts: dict, exported: list[Path]) -> list[dict]:
    """Repositories no export on disk holds, with at least 2 tasks (a recurrence needs a later,
    different task), every task listed."""
    on_disk = set().union(*(repo_names(directory) for directory in exported))
    blocked = set(HELD_OUT) | set(EXCLUDED) | set(UNREADABLE) | on_disk
    return [
        {"repo": repo, "set": "rest", "meta2_exported": False, "tasks": sorted(tasks)}
        for repo, tasks in sorted(counts.items())
        if repo not in blocked and len(tasks) >= 2
    ]


def pool_tasks(pool: Path) -> dict[str, set[str]]:
    """The tasks each plug-pool repository already exported (its instance ids)."""
    found: dict[str, set[str]] = {}
    for path in pool.glob("*__*.jsonl"):
        with path.open() as rows:
            ids = {json.loads(line)["instance_id"] for line in rows}
        found[path.stem.replace("__", "/", 1)] = ids
    return found


def export(entries: list[dict], out_dir: Path) -> None:
    """At most PER_TASK trajectories of each listed task, one JSONL per repository."""
    import export_nebius_sqlglot as single  # noqa: PLC0415  (duckdb lives in the export venv)
    from export_nebius_repos import split_by_repo  # noqa: PLC0415

    out_dir.mkdir(parents=True, exist_ok=True)
    db = single._connect()
    db.execute("CREATE TEMP TABLE wanted (instance_id VARCHAR)")
    db.executemany("INSERT INTO wanted VALUES (?)", [[t] for e in entries for t in e["tasks"]])
    staged = out_dir / "long.partial.jsonl"
    query = (
        f"SELECT {single.COLUMNS} FROM (SELECT *, row_number() OVER (PARTITION BY instance_id "
        f"ORDER BY sha256('{SEED}:' || trajectory_id)) AS pick FROM "
        f"read_parquet('{single.PARQUET_GLOB}') "
        "WHERE instance_id IN (SELECT instance_id FROM wanted)) "
        f"WHERE pick <= {PER_TASK} ORDER BY repo, instance_id, trajectory_id"
    )
    single._with_rate_limit_backoff(
        "exporting long-history rows",
        lambda: db.execute(f"COPY ({query}) TO '{staged}' (FORMAT JSON)"),
    )
    split_by_repo(staged, out_dir, {e["repo"] for e in entries})
    staged.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    one = stages.add_parser("list")
    for flag in ("--counts", "--pool-dir", "--meta2-dir", "--plan", "--out"):
        one.add_argument(flag, type=Path, required=True)
    three = stages.add_parser("list-rest")
    three.add_argument("--counts", type=Path, required=True)
    three.add_argument("--exported", type=Path, nargs="+", required=True)
    three.add_argument("--out", type=Path, required=True)
    two = stages.add_parser("export")
    for flag in ("--list", "--out-dir"):
        two.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "list-rest":
        entries = rest(json.loads(args.counts.read_text()), args.exported)
        args.out.write_text(json.dumps({"rule": ">= 2 tasks, on no disk export", "repos": entries}))
        print(json.dumps({"repos": len(entries), "tasks": sum(len(e["tasks"]) for e in entries)}))
        return
    if args.stage == "export":
        export(json.loads(args.list.read_text())["repos"], args.out_dir)
        return
    plan = json.loads(args.plan.read_text())
    entries = listed(json.loads(args.counts.read_text()), args.pool_dir, args.meta2_dir, plan)
    rule = f">= {MIN_TASKS} tasks outside the plug pool; validation >= {VALIDATION_MIN_TASKS}"
    args.out.write_text(
        json.dumps({"rule": rule, "per_task": PER_TASK, "repos": entries}, indent=1)
    )
    for name in ("scored", "validation"):
        chosen = [e for e in entries if e["set"] == name]
        tasks = sum(len(e["tasks"]) for e in chosen)
        print(json.dumps({"set": name, "repos": len(chosen), "tasks": tasks}))


if __name__ == "__main__":
    main()
