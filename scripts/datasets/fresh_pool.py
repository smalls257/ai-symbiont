"""The fresh repositories for Plug round 4: never in the plug pool, listed for export by the pool's
own task cap, in two tiers fixed before any of their rows is read.

Usage: uv run python scripts/datasets/fresh_pool.py --counts task-counts.json --pool-dir POOL
Usage:   --meta2-dir META2 --out fresh-pool.json

Tier `eligible` is the pool's rule (`repo_pool.eligible`); tier `loosened` relaxes one part of it
(at least 3 tasks instead of 5, trajectories unchanged), the pre-declared fallback if `eligible`
gives too few repos. A repository meta2 exported (one trajectory per task, another experiment) is
kept but marked, so the prereg can disclose or drop it. Counts only; no row is read here.
"""

import argparse
import json
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from symbiont.eval.repo_pool import (  # noqa: E402
    EXCLUDED,
    HELD_OUT,
    MAX_TRAJECTORIES,
    MIN_TRAJECTORIES,
    POOL_SEED,
    UNREADABLE,
    capped_tasks,
    eligible,
)

LOOSE_MIN_TASKS = 3  # the one relaxed part of the rule, declared before any export


def repo_names(directory: Path) -> set[str]:
    """Repositories with an exported `owner__name.jsonl` file in a directory."""
    return {path.stem.replace("__", "/", 1) for path in directory.glob("*__*.jsonl")}


def loosened(counts: dict, strict: set[str]) -> list[str]:
    """Repositories that pass only the relaxed rule."""
    blocked = set(HELD_OUT) | set(EXCLUDED) | set(UNREADABLE) | strict
    return sorted(
        repo
        for repo, tasks in counts.items()
        if repo not in blocked
        and len(tasks) >= LOOSE_MIN_TASKS
        and sum(tasks.values()) >= MIN_TRAJECTORIES
    )


def entry(repo: str, tasks: dict[str, int], tier: str, meta2: set[str]) -> dict:
    """One export entry: the pool's capped whole tasks, its tier and whether meta2 read it."""
    kept = capped_tasks(tasks, POOL_SEED + zlib.crc32(repo.encode()))
    return {
        "repo": repo,
        "tier": tier,
        "meta2_exported": repo in meta2,
        "tasks": kept,
        "trajectories": sum(tasks[task] for task in kept),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--counts", "--pool-dir", "--meta2-dir", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    counts = json.loads(args.counts.read_text())
    used = repo_names(args.pool_dir)
    meta2 = repo_names(args.meta2_dir)
    strict = set(eligible(counts))
    tiers = {
        "eligible": sorted(strict - used),
        "loosened": [r for r in loosened(counts, strict) if r not in used],
    }
    repos = [entry(r, counts[r], tier, meta2) for tier, names in tiers.items() for r in names]
    document = {
        "rule": f"not in the plug pool; eligible as the pool, else >= {LOOSE_MIN_TASKS} tasks and "
        f">= {MIN_TRAJECTORIES} trajectories; whole tasks up to {MAX_TRAJECTORIES} each",
        "seed": POOL_SEED,
        "repos": repos,
    }
    args.out.write_text(json.dumps(document, indent=1))
    summary = {
        tier: {
            "repos": len(names),
            "meta2_exported": sum(r in meta2 for r in names),
        }
        for tier, names in tiers.items()
    }
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
