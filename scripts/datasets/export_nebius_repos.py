"""Count and export repositories of nebius/SWE-rebench-openhands-trajectories (T46 pool, T39).

Periphery, not core: it touches the network. Run on the run machine from the repo root:

    python scripts/datasets/export_nebius_repos.py count \
        --out data/nebius-openhands/task-counts.json
    python scripts/datasets/export_nebius_repos.py export --pool results/repo-pool.json \
        --out-dir data/nebius-openhands/pool

`export-held-out` writes Pillow, dvc and conan (every task) at the pinned dataset revision,
with each task's created_at and base_commit from SWE-rebench, for the scored run only.
`count` reads only the repo and instance_id columns: trajectories per (repo, task), no row
text. `export` writes one JSONL per pool repository with exactly the tasks the pool lists, in
the shape the OpenHands reader takes, and refuses any held-out repository. Each file is read
back through the reader, so a bad export fails here. Needs duckdb (an export-only venv).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_nebius_sqlglot as single  # noqa: E402

from symbiont.eval.repo_pool import HELD_OUT  # noqa: E402
from symbiont.readers import openhands  # noqa: E402

COLUMNS = single.COLUMNS
# Pinned revisions for the scored T46 run (prereg/2026-10-28-note-cost.md).
TRAJECTORIES_REVISION = "35455389ab51bf5e2306bfd436ef72d0f98bf882"
REBENCH_REVISION = "89cdfbab4ab1bd8f5a658bb212d1b63624f4f881"
PINNED_GLOB = f"hf://datasets/{single.DATASET}@{TRAJECTORIES_REVISION}/**/*.parquet"
REBENCH_FILES = ("filtered-00000-of-00001", "test-00001-of-00002")
REBENCH = "hf://datasets/nebius/SWE-rebench@" + REBENCH_REVISION + "/data/{}.parquet"


def count(args: argparse.Namespace) -> None:
    """Trajectories per (repo, task), counts only."""
    db = single._connect()
    rows = single._with_rate_limit_backoff(
        "counting tasks",
        lambda: db.execute(
            f"SELECT repo, instance_id, count(*) FROM read_parquet('{single.PARQUET_GLOB}') "
            "GROUP BY repo, instance_id ORDER BY repo, instance_id"
        ).fetchall(),
    )
    table: dict[str, dict[str, int]] = {}
    for repo, task, n in rows:
        table.setdefault(repo, {})[task] = int(n)
    Path(args.out).write_text(json.dumps(table))
    print(f"{args.out}: {len(table)} repos, {sum(map(len, table.values()))} tasks", file=sys.stderr)


def file_name(repo: str) -> str:
    """The pool file of one repository."""
    return repo.replace("/", "__") + ".jsonl"


def export(args: argparse.Namespace) -> None:
    """One JSONL per pool repository, only the listed tasks; held-out repositories refused."""
    pool = json.loads(Path(args.pool).read_text())
    repos = {entry["repo"]: entry["tasks"] for entry in pool["repos"]}
    refused = sorted(set(repos) & set(HELD_OUT))
    if refused:
        raise SystemExit(f"the pool lists held-out repositories {refused}; refusing to export")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db = single._connect()
    tasks = [task for listed in repos.values() for task in listed]
    db.execute("CREATE TEMP TABLE wanted (instance_id VARCHAR)")
    db.executemany("INSERT INTO wanted VALUES (?)", [[t] for t in tasks])
    staged = out_dir / "pool.partial.jsonl"
    single._with_rate_limit_backoff(
        "exporting pool rows",
        lambda: db.execute(
            f"COPY (SELECT {COLUMNS} FROM read_parquet('{single.PARQUET_GLOB}') "
            "WHERE instance_id IN (SELECT instance_id FROM wanted) "
            f"ORDER BY repo, instance_id, trajectory_id) TO '{staged}' (FORMAT JSON)"
        ),
    )
    split_by_repo(staged, out_dir, set(repos))
    staged.unlink()


def split_by_repo(staged: Path, out_dir: Path, repos: set[str]) -> None:
    """Write each repository's rows to its own file and read each back through the reader."""
    handles = {repo: (out_dir / file_name(repo)).open("w") for repo in repos}
    with staged.open() as rows:
        for line in rows:
            repo = json.loads(line)["repo"]
            if repo not in handles:
                raise SystemExit(f"export returned a row of {repo!r}, which the pool does not list")
            handles[repo].write(line)
    for handle in handles.values():
        handle.close()
    for repo in sorted(repos):
        counts = read_back(out_dir / file_name(repo), repo)
        print(f"{repo}: {counts.rows} trajectories, {counts.tasks} tasks", file=sys.stderr)


def read_back(path: Path, repo: str) -> single.Counts:
    """Read one export through the OpenHands reader; a bad row raises ReadError naming it."""
    sessions, tasks, records = set(), set(), 0
    for record in openhands.read(path, repo):
        sessions.add(record.session_id)
        tasks.add(record.task_id)
        records += 1
    if not sessions:
        raise SystemExit(f"{path}: no rows exported; refusing to call this a dataset")
    return single.Counts(rows=len(sessions), tasks=len(tasks), records=records)


def export_held_out(args: argparse.Namespace) -> None:
    """The held-out repositories for the scored run, every task, at the pinned revision."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db = single._connect()
    staged = out_dir / "held-out.partial.jsonl"
    names = ", ".join(f"'{repo}'" for repo in HELD_OUT)
    single._with_rate_limit_backoff(
        "exporting held-out rows",
        lambda: db.execute(
            f"COPY (SELECT {COLUMNS} FROM read_parquet('{PINNED_GLOB}') WHERE repo IN ({names}) "
            f"ORDER BY repo, instance_id, trajectory_id) TO '{staged}' (FORMAT JSON)"
        ),
    )
    split_by_repo(staged, out_dir, set(HELD_OUT))
    staged.unlink()
    write_meta(db, out_dir)


def write_meta(db: Any, out_dir: Path) -> None:
    """created_at and base_commit of every held-out task, for the hub checkout rule."""
    meta: dict[str, dict[str, str]] = {}
    for name in REBENCH_FILES:
        rows = single._with_rate_limit_backoff(
            "reading task metadata",
            lambda name=name: db.execute(
                "SELECT instance_id, CAST(created_at AS VARCHAR), base_commit "
                f"FROM '{REBENCH.format(name)}'"
            ).fetchall(),
        )
        for task, created, commit in rows:
            meta.setdefault(task, {"created_at": created, "base_commit": commit})
    for repo in HELD_OUT:
        tasks = {r.task_id for r in openhands.read(out_dir / file_name(repo), repo)}
        missing = sorted(t for t in tasks if t not in meta)
        if missing:
            raise SystemExit(f"{repo}: {len(missing)} task(s) without SWE-rebench metadata")
        found = {t: meta[t] for t in sorted(tasks)}
        (out_dir / file_name(repo).replace(".jsonl", ".meta.json")).write_text(json.dumps(found))


def main() -> None:
    """Parse the command line and run one subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    count_parser = sub.add_parser("count")
    count_parser.add_argument("--out", required=True)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--pool", required=True)
    export_parser.add_argument("--out-dir", required=True)
    held_parser = sub.add_parser("export-held-out")
    held_parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    {"count": count, "export": export, "export-held-out": export_held_out}[args.cmd](args)


if __name__ == "__main__":
    main()
