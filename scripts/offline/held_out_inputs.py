"""Held-out repository inputs for the scored T46 run: read, drop refused rows, split, hubs.

Periphery (reads files, clones a repository). The rules are the prereg's
(prereg/2026-10-28-note-cost.md): refused rows are dropped and counted, tasks split with test
fraction 0.3 and seed 20261029, hubs from the median-created TRAIN task's base commit.
"""

import argparse
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from symbiont.eval import selection as sel
from symbiont.eval.net_benefit import PRIMARY_COST
from symbiont.eval.offline import ReplayContext, drop_taskless, hub_modules, split_by_task
from symbiont.eval.repo_pool import HELD_OUT
from symbiont.readers import openhands
from symbiont.readers.errors import ReadError
from symbiont.store.references import build_references

log = logging.getLogger("note-cost-scored")
HUB_CUTOFF = 0.5


def file_of(data_dir: Path, repo: str, suffix: str = ".jsonl") -> Path:
    """The exported file of one repository."""
    return data_dir / (repo.replace("/", "__") + suffix)


SMOKE_TASKS = 12


def split_repo(data_dir: Path, repo: str, *, smoke: bool = False) -> dict[str, Any]:
    """Sessions of one repository split by task (test fraction 0.3, seed 20261029).

    Smoke keeps a few TRAIN-split tasks and splits them again: no real TEST task is replayed.
    """
    records, refused = readable_records(file_of(data_dir, repo), repo)
    sessions, dropped = drop_taskless(sel.group_sessions(records))
    train_ids, test_ids = split_by_task(
        [s[0].task_id for s in sessions], test_fraction=sel.TEST_FRACTION, seed=sel.SEED
    )
    if smoke:
        keep = set(sorted(train_ids)[:SMOKE_TASKS])
        sessions = [s for s in sessions if s[0].task_id in keep]
        train_ids, test_ids = split_by_task(
            sorted(keep), test_fraction=sel.TEST_FRACTION, seed=sel.SEED
        )
    ordered = sel.replay_order(sessions)
    return {
        "train": [s for s in ordered if s[0].task_id in train_ids],
        "test": [s for s in ordered if s[0].task_id in test_ids],
        "train_ids": train_ids,
        "dropped_taskless": dropped,
        "refused_by_reader": refused,
    }


def readable_records(path: Path, repo: str) -> tuple[list, int]:
    """Records of every row the reader reads; refused rows are dropped, counted and logged."""
    records, refused = [], 0
    for row in openhands.read_each_row(path, repo):
        if isinstance(row, ReadError):
            refused += 1
            log.warning("dropped a trajectory the reader refuses (prereg rule): %s", row)
            continue
        records += row
    return records, refused


def split_counts(parts: dict[str, Any]) -> dict[str, int]:
    """Tasks, sessions and steps per split: counts only, no label and no metric."""
    found = {
        "sessions_dropped_taskless": parts["dropped_taskless"],
        "trajectories_refused_by_reader": parts["refused_by_reader"],
    }
    for name in ("train", "test"):
        found[f"tasks_{name}"] = len({s[0].task_id for s in parts[name]})
        found[f"sessions_{name}"] = len(parts[name])
        found[f"steps_{name}"] = sum(len(s) for s in parts[name])
    return found


def split(args: argparse.Namespace) -> None:
    """Print the per-split counts the prereg records before any metric exists."""
    counts = {repo: split_counts(split_repo(Path(args.data_dir), repo)) for repo in HELD_OUT}
    print(json.dumps(counts, indent=1))


def hub_context(data_dir: Path, repo: str, train_ids: frozenset[str]) -> tuple[ReplayContext, dict]:
    """Check out the median-created TRAIN task's base commit and build the replay context."""
    meta = json.loads(file_of(data_dir, repo, ".meta.json").read_text())
    task = sel.median_task({t: m["created_at"] for t, m in meta.items()}, train_ids)
    commit = meta[task]["base_commit"]
    with tempfile.TemporaryDirectory(prefix="hub-") as tmp:
        references = checkout_references(repo, commit, Path(tmp))
    hubs = hub_modules(references, HUB_CUTOFF)
    log.info("%s hub checkout: task %s at %s; hubs %s", repo, task, commit, sorted(hubs))
    ctx = ReplayContext(references=references, hubs=hubs, false_alarm_cost=PRIMARY_COST)
    return ctx, {
        "task_id": task,
        "base_commit": commit,
        "hub_modules": sorted(hubs),
        "reference_files": len(references),
    }


def checkout_references(repo: str, commit: str, workdir: Path) -> dict[str, frozenset[str]]:
    """Fetch one commit by hash (it may be off every branch) and map test references."""
    dest = workdir / "checkout"
    dest.mkdir()
    for step in (
        ["init", "--quiet"],
        ["remote", "add", "origin", f"https://github.com/{repo}"],
        ["fetch", "--quiet", "--depth", "1", "origin", commit],
        ["checkout", "--quiet", "FETCH_HEAD"],
    ):
        subprocess.run(["git", "-C", str(dest), *step], check=True)
    return build_references(dest)
