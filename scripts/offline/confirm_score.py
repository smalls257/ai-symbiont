"""The scored T48 step: ship from the pool, re-derive the thresholds, count tox, dask and PyBaMM.

Called by `run_confirm_scored.py score --scored --prereg prereg/2026-10-28-confirm.md`. Before any
confirm metric: the prereg is frozen, the settings file's sha256 is the pinned one, and the
thresholds re-derived from the pool equal the file's. Each job ships one (row, seed) from the 80
pool training repositories and scores one target, reusing the T47 job code unchanged.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import fly_ablation_arms as fa
import numpy as np
import run_fly_ablation as ra
import run_repo_curve as rc
import run_selection as g6

from symbiont.eval import confirm_report as cr
from symbiont.eval import selection as sel
from symbiont.eval.batch_refit import LogisticScorer
from symbiont.eval.net_benefit import PRIMARY_COST
from symbiont.eval.note_cost_logistic import fit_logistic
from symbiont.eval.note_cost_options import count_stack, prepare
from symbiont.eval.note_cost_ranking import ranking
from symbiont.eval.note_cost_scored_report import PRIMARY, learner_counts, registered_options
from symbiont.eval.note_cost_scored_report import Layout as T46Layout
from symbiont.eval.note_delivery import NoteTrace
from symbiont.eval.offline import ReplayContext, drop_taskless
from symbiont.eval.regime_replay import frozen_risks, live_risks, refit_risks, train_online
from symbiont.readers import openhands
from symbiont.readers.errors import ReadError

log = logging.getLogger("confirm-score")
CONFIRM = ("tox-dev/tox", "dask/dask", "pybamm-team/PyBaMM")
PREREG_NAME = "2026-10-28-confirm.md"
SETTINGS_SHA256 = "06900a289fd34ab308e5e97b0c8ad80ed3ac9088be658919c042db6af0af2877"
N_BOOT = 2000
POOL = "pool"
SHIPPED = 80
# row -> (T47 arm, regime); counters and the classifier are shipped by their own jobs
ONLINE = {
    cr.DENSE: ("dense combined backprop", "R2"),
    cr.FLY: ("fly as is", "R1"),
    cr.FLY_FIXED: ("fly combined", "R1"),
}
POOL_SCORING: list[str] = []
REFUSED: dict[str, int] = {}


def settings_sha(path: Path, *, enforce: bool) -> str:
    """sha256 of the settings file; a scored run raises unless it is the pinned one (rule 7).

    An exploratory run (a smoke of this code on pool data) records the sha and warns.
    """
    found = hashlib.sha256(path.read_bytes()).hexdigest()
    if found != SETTINGS_SHA256:
        if enforce:
            raise SystemExit(f"{path}: sha256 {found} is not the pinned {SETTINGS_SHA256}")
        log.warning("EXPLORATORY: settings sha256 %s is not the pinned one", found)
    return found


def load_confirm(path: Path, repo: str) -> list:
    """Readable sessions in the seeded replay order; refused rows dropped and counted."""
    rows = list(openhands.read_each_row(path, repo))
    readable = [row for row in rows if not isinstance(row, ReadError)]
    REFUSED[repo] = len(rows) - len(readable)
    sessions, _ = drop_taskless(sel.group_sessions([r for row in readable for r in row]))
    return list(sel.replay_order(sessions))


def prepare_confirm(confirm_dir: Path, workers: int) -> None:
    """Confirm repositories beside the pool: pool-style labels, features from one counters pass."""
    POOL_SCORING[:] = rc.SCORING
    ctx = ReplayContext(references={}, hubs=frozenset(), false_alarm_cost=PRIMARY_COST)
    for repo in CONFIRM:
        rc.REPOS[repo] = (
            load_confirm(confirm_dir / (repo.replace("/", "__") + ".jsonl"), repo),
            ctx,
        )
    for repo, _, columns in g6.pool_map(rc.warm, CONFIRM, workers):
        rc.COLUMNS[repo] = columns
    ra.build_projects()


def jobs() -> list[tuple[str, int, str]]:
    """(row, seed, target): the slow DenseNet refits first."""
    targets = (*CONFIRM, POOL)
    found = [(cr.DENSE, s, t) for t in targets for s in sel.WIRING_SEEDS]
    found += [
        (row, s, t) for row in (cr.FLY_FIXED, cr.FLY) for t in targets for s in sel.WIRING_SEEDS
    ]
    return found + [(row, 0, t) for row in (cr.COUNTERS, cr.CLASSIFIER) for t in targets]


def score_job(job: tuple[str, int, str]) -> tuple[tuple[str, int, str], dict[str, Any]]:
    """Ship one (row, seed) and record its risks on one target."""
    row, seed, target = job
    started = time.time()
    rc.SCORING[:] = POOL_SCORING if target == POOL else [target]
    times: list[float] = []
    if row == cr.COUNTERS:
        risks = rc.curve_job(("counters", 0, None, SHIPPED))
    elif row == cr.CLASSIFIER:
        risks = classifier_risks()
    else:
        risks = online_risks(row, seed, times)
    log.info("%s seed %d on %s (%.0fs)", row, seed, target, time.time() - started)
    return job, {"risks": risks, "refit_s": times}


def classifier_risks() -> dict[str, list[float]]:
    """The class-weighted classifier (L2 1000) fit on the 80 repositories, frozen (R1)."""
    train = rc.TRAIN_ORDER[:SHIPPED]
    rows = np.vstack([rc.COLUMNS[r]["features"] for r in train])
    labels = np.concatenate([np.concatenate(rc.COLUMNS[r]["followed"]) for r in train]).astype(
        float
    )
    model = fit_logistic(rows, labels, ra.L2)
    return ra.by_repo(lambda project: frozen_risks(LogisticScorer(model), project, model.coef))


def online_risks(row: str, seed: int, times: list[float]) -> dict[str, list[float]]:
    """A fly or DenseNet row: shipped online, then its registered regime on the target."""
    name, regime = ONLINE[row]
    arm = fa.ARMS[name]
    scorer = arm.build(seed, ra.FIXED[SHIPPED])
    projects = [ra.PROJECTS[r] for r in rc.TRAIN_ORDER[:SHIPPED]]
    shipped = train_online(scorer, projects, scorer.initial_state(0))
    if regime == "R1":
        return ra.by_repo(lambda project: live_risks(scorer, project, shipped))
    reader, refit = fa.refit_for(arm, scorer, shipped)
    return ra.by_repo(lambda project: refit_risks(reader, fa.timed(refit, times), project, shipped))


def confirm_traces(repo: str, risks: list[float]) -> tuple[NoteTrace, ...]:
    """Per-session traces of one confirm repository, keyed by the session's task id."""
    sessions, columns = rc.REPOS[repo][0], rc.COLUMNS[repo]
    found, start = [], 0
    for session, followed, boundary in zip(
        sessions, columns["followed"], columns["boundary"], strict=True
    ):
        stop = start + len(followed)
        found.append(
            NoteTrace(
                session[0].task_id, tuple(followed), tuple(risks[start:stop]), tuple(boundary)
            )
        )
        start = stop
    if start != len(risks):
        raise ValueError(f"{repo}: {len(risks)} risks for {start} steps")
    return tuple(found)


def settings_of(risks: dict[str, list[float]]) -> dict[str, dict[str, Any]]:
    """Each registered option's (note, warning) thresholds chosen on the pool scoring traces."""
    traces = rc.traces_of(risks)
    arm = prepare(traces, sorted({t.task_id for t in traces}))
    found = {}
    for option in registered_options():
        # Not note_cost_scored_report.train_stack: it caches by id(traces), and a traces tuple
        # built and freed here would hand its id, and its cached stack, to the next learner.
        stack = count_stack(arm, option.rule, option.tiers)
        index, score = option.choose(stack.counts)
        note, warn = stack.settings[index]
        found[option.key] = {
            "note_at_or_above": _finite(note),
            "warning_at_or_above": _finite(warn),
            "pool_score": score,
        }
    return found


def _finite(threshold: float) -> float | None:
    """A threshold, or None for a tier that never speaks (strict JSON has no Infinity)."""
    return None if threshold == float("inf") else threshold


def check_settings(found: dict, settings: dict[str, Any]) -> None:
    """Thresholds re-derived on the pool must equal the pinned file's, every one."""
    for (row, seed, target), result in found.items():
        if target != POOL:
            continue
        again = json.loads(json.dumps(settings_of(result["risks"])))
        if again != settings[row][f"seed {seed}"]:
            raise SystemExit(
                f"{row} seed {seed}: thresholds re-derived on the pool differ from the file"
            )


def auc_of(by_seed: dict[int, dict[str, list[float]]]) -> float:
    """Seed-mean pooled ranking AUC over the confirm repositories."""
    followed = np.concatenate([np.concatenate(rc.COLUMNS[r]["followed"]) for r in CONFIRM])
    return float(
        np.mean(
            [
                ranking(np.concatenate([risks[r] for r in CONFIRM]), followed)["roc_auc"]
                for risks in by_seed.values()
            ]
        )
    )


def by_row(found: dict) -> dict[str, dict[int, dict[str, list[float]]]]:
    """row -> seed -> confirm repository -> risks."""
    rows: dict[str, dict[int, dict[str, list[float]]]] = {}
    for (row, seed, target), result in found.items():
        if target != POOL:
            rows.setdefault(row, {}).setdefault(seed, {}).update(result["risks"])
    return rows


def t46_self_check(found: dict, settings: dict[str, Any]) -> dict[str, float]:
    """Counts at the pinned thresholds against the T46 scorer on one pool repository."""
    option = next(o for o in registered_options() if o.key == PRIMARY)
    repo, gaps = POOL_SCORING[0], {}
    for row in (cr.COUNTERS, cr.FLY_FIXED):
        train = rc.traces_of(found[(row, 0, POOL)]["risks"])
        test = tuple(t for t in train if t.task_id == repo)
        lay = T46Layout((repo,), {repo: [repo]}, np.ones((1, 1)))
        theirs, _ = learner_counts({0: {repo: [(train, test)]}}, option, lay)
        at = cr.thresholds_of(settings[row]["seed 0"][PRIMARY])
        ours = cr.fixed_counts(test, [repo], at, option)
        gaps[row] = float(np.max(np.abs(theirs - ours)))
        if gaps[row] != 0.0:
            raise SystemExit(f"{row}: counts differ from the T46 scorer by {gaps[row]}")
    return gaps
