"""Per-repository episodes for T39: step features, labels, boundaries and the counters' risks.

One counters replay per pool repository, from a fresh state with empty history (each
repository on its own, as T46's warm pass). Features do not depend on the learner, so the
filler rows reuse them without replaying again. The file holds numbers only and lives under
the gitignored data/ directory.

    meta_start_episodes.py --pool results/repo-pool.json \
        --data-dir data/nebius-openhands/pool --out data/t39-episodes.npz
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import run_note_cost as nc
import run_penalized as t36
import run_repo_curve as curve
import run_selection as g6

from symbiont.eval.meta_start import Episode
from symbiont.eval.net_benefit import PRIMARY_COST
from symbiont.eval.note_delivery import boundary_steps
from symbiont.eval.offline import ReplayContext, Start, replay
from symbiont.eval.warning_budget_metrics import RiskRecorder

log = logging.getLogger("t39-episodes")
PATHS: dict[str, Path] = {}


@dataclass(frozen=True)
class RepoSteps:
    """Everything a row needs about one repository, sessions in replay order."""

    episode: Episode
    boundary: tuple[np.ndarray, ...]
    counters_risk: tuple[np.ndarray, ...]
    task_ids: tuple[str, ...] = ()  # per session; stored for the held-out repositories only

    def all_features(self) -> np.ndarray:
        """Every step's features, stacked."""
        return np.vstack(self.episode.features)

    def all_followed(self) -> np.ndarray:
        """Every step's label, concatenated."""
        return np.concatenate(self.episode.followed)


def episode_of(repo: str) -> dict[str, np.ndarray]:
    """One counters replay of a repository: its columns as flat arrays."""
    started = time.time()
    sessions = curve.load_repo(PATHS[repo], repo)
    ctx = ReplayContext(references={}, hubs=frozenset(), false_alarm_cost=PRIMARY_COST)
    risks = RiskRecorder(t36.make_learner("counters", 0, None))
    recorder = nc.FeatureRecorder(risks)
    scores = replay(recorder, sessions, Start.fresh(), ctx=ctx, seed=g6.REPLAY_SEED).scores
    if any(r is None for r in risks.risks):
        raise ValueError(f"{repo}: counters gave a step with no risk")
    log.info("%s: %d sessions (%.0fs)", repo, len(sessions), time.time() - started)
    return {
        "x": np.vstack(recorder.rows),
        "y": np.concatenate([s.followed for s in scores.per_session]).astype(bool),
        "b": np.concatenate([boundary_steps(s) for s in sessions]).astype(bool),
        "n": np.array([len(s.followed) for s in scores.per_session]),
        "c": np.array(risks.risks, dtype=np.float64),
    }


def build(args: argparse.Namespace) -> None:
    """Replay counters over every pool repository and store the columns."""
    pool = json.loads(Path(args.pool).read_text())["repos"]
    repos = [e["repo"] for e in pool]
    PATHS.update({r: Path(args.data_dir) / (r.replace("/", "__") + ".jsonl") for r in repos})
    columns = g6.pool_map(episode_of, repos, args.workers)
    arrays = {f"{i}.{k}": v for i, c in enumerate(columns) for k, v in c.items()}
    np.savez_compressed(args.out, repos=np.array(repos), **arrays)
    steps = sum(len(c["y"]) for c in columns)
    log.info("wrote %s: %d repositories, %d steps", args.out, len(repos), steps)


def load(path: str) -> dict[str, RepoSteps]:
    """The stored episodes, by repository name."""
    stored = np.load(path)
    found = {}
    for index, repo in enumerate(stored["repos"].tolist()):
        cuts = np.cumsum(stored[f"{index}.n"])[:-1]

        def split(key: str, cuts: np.ndarray = cuts, at: int = index) -> tuple[np.ndarray, ...]:
            return tuple(np.split(stored[f"{at}.{key}"], cuts))

        episode = Episode(repo, split("x"), split("y"))
        tasks = tuple(stored[f"{index}.t"].tolist()) if f"{index}.t" in stored else ()
        found[repo] = RepoSteps(episode, split("b"), split("c"), tasks)
    return found


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and build the episodes file."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    for name in ("pool", "data-dir", "out"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--workers", type=int, default=16)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    build(parser.parse_args(argv))


if __name__ == "__main__":
    main()
