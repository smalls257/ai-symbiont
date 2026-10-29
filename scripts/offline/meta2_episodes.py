"""META2 episodes: one trajectory per task, tasks by issue date, one counters pass per repository.

Each task's best-ranked readable trajectory (`meta2_tasks.first_readable`); refused rows dropped
and counted. Labels follow the pool rule for every role (a pain point within 5 steps, empty
references, no hub filter). Held-out repositories get `counts` only until the prereg is frozen.
Usage: meta2_episodes.py {build|counts} --data-dir D --out D/episodes --roles ...
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import run_note_cost as nc
import run_penalized as t36
import run_selection as g6

from symbiont.eval import meta2_tasks as mt
from symbiont.eval import selection as sel
from symbiont.eval.net_benefit import PRIMARY_COST
from symbiont.eval.note_delivery import boundary_steps
from symbiont.eval.offline import ReplayContext, Start, replay
from symbiont.eval.warning_budget_metrics import RiskRecorder
from symbiont.readers import openhands
from symbiont.readers.errors import ReadError

log = logging.getLogger("meta2-episodes")
PLAN: dict[str, Any] = {}
DATA: list[Path] = []
LABEL_RULE = "pain point within 5 steps, same session; empty references, no hub filter"


def sessions_of(repo: str) -> tuple[list, int]:
    """One readable session per planned task, in issue order, and the refused row count."""
    entry = PLAN["repos"][repo]
    rows = list(openhands.read_each_row(DATA[0] / (repo.replace("/", "__") + ".jsonl"), repo))
    readable = [row for row in rows if not isinstance(row, ReadError)]
    by_id = {s[0].session_id: s for s in sel.group_sessions([r for row in readable for r in row])}
    chosen = [
        by_id[mt.first_readable(task, entry["picks"][task], by_id)] for task in entry["tasks"]
    ]
    return chosen, len(rows) - len(readable)


def episode_of(repo: str) -> tuple[str, dict[str, np.ndarray], int]:
    """One counters replay of a repository in issue order: its columns as flat arrays."""
    started = time.time()
    sessions, refused = sessions_of(repo)
    ctx = ReplayContext(references={}, hubs=frozenset(), false_alarm_cost=PRIMARY_COST)
    risks = RiskRecorder(t36.make_learner("counters", 0, None))
    recorder = nc.FeatureRecorder(risks)
    scores = replay(recorder, sessions, Start.fresh(), ctx=ctx, seed=g6.REPLAY_SEED).scores
    if any(r is None for r in risks.risks):
        raise ValueError(f"{repo}: counters gave a step with no risk")
    log.info("%s: %d tasks (%.0fs)", repo, len(sessions), time.time() - started)
    columns = {
        "x": np.vstack(recorder.rows),
        "y": np.concatenate([s.followed for s in scores.per_session]).astype(bool),
        "b": np.concatenate([boundary_steps(s) for s in sessions]).astype(bool),
        "n": np.array([len(s.followed) for s in scores.per_session]),
        "c": np.array(risks.risks, dtype=np.float64),
        "t": np.array([s[0].task_id for s in sessions]),
    }
    return repo, columns, refused


def load_plan(args: argparse.Namespace) -> Path:
    """Read the plan once per process; returns the output directory, created."""
    DATA.append(Path(args.data_dir))
    PLAN.update(json.loads((DATA[0] / "plan.json").read_text()))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def count_of(repo: str) -> tuple[str, dict[str, int]]:
    """Tasks, steps and refused rows of one repository, without any label."""
    sessions, refused = sessions_of(repo)
    return repo, {
        "tasks": len(sessions),
        "steps": sum(len(s) for s in sessions),
        "rows_refused": refused,
    }


def counts(args: argparse.Namespace) -> None:
    """Counts only, for the roles named (the held-out repositories before the freeze)."""
    out = load_plan(args)
    repos = [r for role in args.roles for r in PLAN["split"][role]]
    found = dict(g6.pool_map(count_of, repos, args.workers))
    (out / f"counts-{'-'.join(args.roles)}.json").write_text(json.dumps(found, indent=1))
    log.info("counts %s", found)


def build(args: argparse.Namespace) -> None:
    """Every repository of the roles named: its episode, one file per role, a summary."""
    out = load_plan(args)
    repos = [r for role in args.roles for r in PLAN["split"][role]]
    found = {r: (c, n) for r, c, n in g6.pool_map(episode_of, repos, args.workers)}
    summary: dict[str, Any] = {"label_rule": LABEL_RULE, "roles": {}}
    for role in args.roles:
        repos = PLAN["split"][role]
        arrays = {f"{i}.{k}": v for i, r in enumerate(repos) for k, v in found[r][0].items()}
        np.savez_compressed(out / f"{role}.npz", repos=np.array(repos), **arrays)
        summary["roles"][role] = {
            r: {
                "tasks": len(found[r][0]["n"]),
                "steps": int(found[r][0]["n"].sum()),
                "trouble_steps": int(found[r][0]["y"].sum()),
                "rows_refused": found[r][1],
            }
            for r in repos
        }
    (out / f"summary-{'-'.join(args.roles)}.json").write_text(json.dumps(summary, indent=1))
    log.info("wrote %s", out)


def main() -> None:
    """Parse the command line and build the episode files."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("step", choices=("build", "counts"))
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--roles", nargs="+", choices=("train", "validation", "held_out"))
    parser.add_argument("--workers", type=int, default=10)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    args = parser.parse_args()
    if args.step == "build" and "held_out" in args.roles:
        raise SystemExit("held-out episodes carry labels: build them only for the scored run")
    {"build": build, "counts": counts}[args.step](args)


if __name__ == "__main__":
    main()
