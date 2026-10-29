"""Export META2's repositories: one trajectory per task (and a spare), issue dates, the split.

Periphery (network; duckdb from the dev group). `ids` reads only ids at the pinned revision and
each task's created_at; `export` fixes the split from those counts alone, before any row is
read (`symbiont.eval.meta2_tasks`), then writes one JSONL per repository and a plan file.
Usage: export_meta2_repos.py ids --out-dir D
       export_meta2_repos.py export --out-dir D --pool results/repo-pool.json --seen-dir DIR...
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_nebius_repos as pinned  # noqa: E402
import export_nebius_sqlglot as single  # noqa: E402

from symbiont.eval import meta2_tasks as mt  # noqa: E402


def ids(args: argparse.Namespace) -> None:
    """Trajectory ids per (repo, task) and every task's issue date; no trajectory text."""
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db = single._connect()
    rows = single._with_rate_limit_backoff(
        "reading trajectory ids",
        lambda: db.execute(
            f"SELECT repo, instance_id, trajectory_id FROM read_parquet('{pinned.PINNED_GLOB}')"
        ).fetchall(),
    )
    table: dict[str, dict[str, list[str]]] = {}
    for repo, task, trajectory in rows:
        table.setdefault(repo, {}).setdefault(task, []).append(trajectory)
    (out / "ids.json").write_text(json.dumps(table))
    created: dict[str, str] = {}
    for name in pinned.REBENCH_FILES:
        found = single._with_rate_limit_backoff(
            "reading issue dates",
            lambda name=name: db.execute(
                "SELECT instance_id, CAST(created_at AS VARCHAR) "
                f"FROM '{pinned.REBENCH.format(name)}'"
            ).fetchall(),
        )
        for task, when in found:
            created.setdefault(task, when)
    (out / "created.json").write_text(json.dumps(created))
    print(f"{len(table)} repos, {len(rows)} trajectories, {len(created)} dated", file=sys.stderr)


def seen_repos(pool: Path, seen_dirs: list[str]) -> set[str]:
    """Every repository an earlier run read: the pool file and each export directory's files."""
    names = {entry["repo"] for entry in json.loads(pool.read_text())["repos"]}
    for directory in seen_dirs:
        for path in Path(directory).glob("*.jsonl"):
            names.add(path.stem.replace("__", "/", 1))
    return names


def plan_of(table: dict, created: dict, seen: set[str]) -> dict:
    """The split from task counts alone, then each repository's tasks by date and its picks.

    A repository with an undated task cannot be put in issue order; it is left out whole and
    named in the plan (SWE-rebench's two pinned files date every task but a few repositories').
    """
    undated = sorted(r for r, tasks in table.items() if any(not created.get(t) for t in tasks))
    dated = {r: len(t) for r, t in table.items() if r not in undated}
    split = mt.split_repos(dated, seen)
    repos = {}
    for repo in (*split.held_out, *split.validation, *split.train):
        ordered = mt.by_issue_date(table[repo], created)
        kept = mt.kept_tasks(split.role_of(repo), ordered)
        repos[repo] = {
            "role": split.role_of(repo),
            "tasks": kept,
            "created_at": [created[t] for t in kept],
            "picks": {t: mt.picks(table[repo][t]) for t in kept},
        }
    return {
        "seed": mt.SEED,
        "seen": sorted(seen),
        "undated_left_out": undated,
        "split": split.__dict__,
        "repos": repos,
    }


def export(args: argparse.Namespace) -> None:
    """Fix the plan, then write each repository's picked trajectories to its own file."""
    out = Path(args.out_dir)
    table = json.loads((out / "ids.json").read_text())
    created = json.loads((out / "created.json").read_text())
    plan = plan_of(table, created, seen_repos(Path(args.pool), args.seen_dir))
    (out / "plan.json").write_text(json.dumps(plan, indent=1))
    wanted = [t for e in plan["repos"].values() for p in e["picks"].values() for t in p]
    db = single._connect()
    db.execute("CREATE TEMP TABLE wanted (trajectory_id VARCHAR)")
    db.executemany("INSERT INTO wanted VALUES (?)", [[t] for t in wanted])
    staged = out / "meta2.partial.jsonl"
    single._with_rate_limit_backoff(
        "exporting picked rows",
        lambda: db.execute(
            f"COPY (SELECT {single.COLUMNS} FROM read_parquet('{pinned.PINNED_GLOB}') "
            "WHERE trajectory_id IN (SELECT trajectory_id FROM wanted) "
            f"ORDER BY repo, instance_id, trajectory_id) TO '{staged}' (FORMAT JSON)"
        ),
    )
    pinned.write_by_repo(staged, out, set(plan["repos"]))
    staged.unlink()
    for role, repos in plan["split"].items():
        print(f"{role}: {len(repos)} repositories", file=sys.stderr)


def main() -> None:
    """Parse the command line and run one subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ids_parser = sub.add_parser("ids")
    ids_parser.add_argument("--out-dir", required=True)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--out-dir", required=True)
    export_parser.add_argument("--pool", required=True)
    export_parser.add_argument("--seen-dir", action="append", default=[])
    args = parser.parse_args()
    {"ids": ids, "export": export}[args.cmd](args)


if __name__ == "__main__":
    main()
