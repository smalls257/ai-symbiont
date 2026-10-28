"""Pillow, dvc and conan for the scored T39 run: counts first, then episodes. Periphery script.

`counts` prints, per repository, refused trajectories, tasks, sessions, steps and the early
window: no label, risk or metric. `episodes` replays each repository whole from empty history with
T46's seeded order, hub checkout and labels, and stores what the rows need under data/. PYTHONPATH
must hold src, scripts/offline and scripts/datasets.
Usage: meta_start_held_out.py {counts|episodes} --data-dir ... --out ...
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import run_note_cost as nc
import run_note_cost_scored as t46
import run_selection as g6

from symbiont.core.counters import Counters
from symbiont.eval import selection as sel
from symbiont.eval.meta_start import EARLY_SESSIONS
from symbiont.eval.note_delivery import boundary_steps
from symbiont.eval.offline import Start, drop_taskless, replay, split_by_task
from symbiont.eval.repo_pool import HELD_OUT
from symbiont.eval.warning_budget_metrics import RiskRecorder

log = logging.getLogger("t39-held-out")
DATA_DIR: list[Path] = []


def whole_repo(data_dir: Path, repo: str) -> dict[str, Any]:
    """Every readable session of one repository in T46's seeded replay order."""
    records, refused = t46.readable_records(t46.file_of(data_dir, repo), repo)
    sessions, dropped = drop_taskless(sel.group_sessions(records))
    return {"sessions": list(sel.replay_order(sessions)), "refused": refused, "taskless": dropped}


def counts_of(parts: dict[str, Any]) -> dict[str, int]:
    """Counts only: refused trajectories, tasks, sessions, steps, and the early window's."""
    sessions = parts["sessions"]
    early = sessions[:EARLY_SESSIONS]
    return {
        "trajectories_refused_by_reader": parts["refused"],
        "sessions_dropped_taskless": parts["taskless"],
        "tasks": len({s[0].task_id for s in sessions}),
        "sessions": len(sessions),
        "steps": sum(len(s) for s in sessions),
        "early_sessions": len(early),
        "early_steps": sum(len(s) for s in early),
        "early_tasks": len({s[0].task_id for s in early}),
    }


def counts(args: argparse.Namespace) -> None:
    """Print the counts table the prereg records before any metric."""
    found = {repo: counts_of(whole_repo(Path(args.data_dir), repo)) for repo in HELD_OUT}
    print(json.dumps(found, indent=1))


def episode_of(repo: str) -> dict[str, Any]:
    """T46's hub checkout and labels; one counters replay of the whole repository."""
    parts = whole_repo(DATA_DIR[0], repo)
    sessions = parts["sessions"]
    train_ids, _ = split_by_task(
        [s[0].task_id for s in sessions], test_fraction=sel.TEST_FRACTION, seed=sel.SEED
    )
    ctx, hub = t46.hub_context(DATA_DIR[0], repo, train_ids)
    risks = RiskRecorder(Counters(min_count=1, hubs=ctx.hubs))
    recorder = nc.FeatureRecorder(risks)
    scores = replay(recorder, sessions, Start.fresh(), ctx=ctx, seed=g6.REPLAY_SEED).scores
    if any(r is None for r in risks.risks):
        raise ValueError(f"{repo}: counters gave a step with no risk")
    return {
        "arrays": {
            "x": np.vstack(recorder.rows),
            "y": np.concatenate([s.followed for s in scores.per_session]).astype(bool),
            "b": np.concatenate([boundary_steps(s) for s in sessions]).astype(bool),
            "n": np.array([len(s.followed) for s in scores.per_session]),
            "c": np.array(risks.risks, dtype=np.float64),
            "t": np.array([s[0].task_id for s in sessions]),
        },
        "hub": hub,
        "counts": counts_of(parts),
    }


def episodes(args: argparse.Namespace) -> None:
    """Build the held-out episodes file and its hub and counts record (numbers and ids)."""
    DATA_DIR[:] = [Path(args.data_dir)]
    built = g6.pool_map(episode_of, list(HELD_OUT), len(HELD_OUT))
    arrays = {f"{i}.{k}": v for i, b in enumerate(built) for k, v in b["arrays"].items()}
    np.savez_compressed(args.out, repos=np.array(HELD_OUT), **arrays)
    record = {
        r: {"hub": b["hub"], "counts": b["counts"]} for r, b in zip(HELD_OUT, built, strict=True)
    }
    Path(args.out).with_suffix(".json").write_text(json.dumps(record, indent=1))
    log.info("wrote %s", args.out)


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run one subcommand."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("counts", "episodes"):
        each = sub.add_parser(name)
        each.add_argument("--data-dir", required=True)
        if name == "episodes":
            each.add_argument("--out", required=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    args = parser.parse_args(argv)
    {"counts": counts, "episodes": episodes}[args.cmd](args)


if __name__ == "__main__":
    main()
