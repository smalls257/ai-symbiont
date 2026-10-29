"""META2's jobs: every row's per-task risks on the scoring repositories, one job per (row, seed).

Module state is filled once by `prepare` and inherited by forked workers. Every job fits only
on training repositories (input gain, trouble share, starts, broad weights, classifier) and
learns on a scoring repository only from the tasks before the one it scores. Fitted starts and
broad weights are saved, so a later scored run reuses them instead of refitting.
"""

import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import meta2_fit as mf
import meta2_inputs as md
import meta2_torch as mtorch
import numpy as np
import torch

from symbiont.eval.meta2_replay import (
    L2,
    META2_CALIBRATOR_RATE,
    RepoTasks,
    calibrated_task,
    calibrator_after,
    own_logistic_risks,
    refit_logistic_risks,
    sequential_risks,
)
from symbiont.eval.note_cost_logistic import fit_logistic, predict

log = logging.getLogger("meta2-jobs")
MAML_LRS = (1e-3, 1e-2)  # Adam outer step sizes; validation value picks one
BROAD_EPOCHS = (1, 2, 4)
FINE_TUNE_STEPS = (5, 20, 80)  # the few-shot step budget; validation value picks one
IN_DOMAIN_STEPS = 300  # the ceiling: an ample budget on all of a repository's other tasks
TRAIN: dict[str, RepoTasks] = {}
SCORING: dict[str, RepoTasks] = {}
FIXED: list[md.Fixed] = []
CODES: dict[tuple[str, int], dict[str, list[np.ndarray]]] = {}
STARTS: list[Path] = []
Risks = dict[str, list[np.ndarray]]


def prepare(train: dict[str, RepoTasks], scoring: dict[str, RepoTasks], starts: Path) -> None:
    """Fill the module state the workers inherit."""
    TRAIN.update(train)
    SCORING.update(scoring)
    FIXED.append(md.fixed_from(train))
    starts.mkdir(parents=True, exist_ok=True)
    STARTS.append(starts)
    torch.set_num_threads(1)


def net_of(name: str, seed: int) -> mf.Net:
    """One network at one wiring seed with its unroll and cold state."""
    rule = md.network(name, seed, FIXED[0])
    if name == md.FLY:
        unroll: Any = mtorch.FlyUnroll(META2_CALIBRATOR_RATE)
    else:
        unroll = mtorch.DenseUnroll(rule.dense, META2_CALIBRATOR_RATE)
    return mf.Net(rule, unroll, md.cold_state(rule))


def encoded(net: mf.Net, repos: dict[str, RepoTasks], key: tuple[str, int]) -> Any:
    """Per repository, each task's encoding; the fly's codes are cached per process."""
    if not net.is_fly:
        return lambda repo: [net.rule.encode(x, net.cold) for x in repos[repo].features]
    if key not in CODES:
        CODES[key] = md.encode_all(net.rule, {**TRAIN, **SCORING})
    return lambda repo: CODES[key][repo]


def online_on_scoring(net: mf.Net, params: mf.Params, key: tuple[str, int]) -> Risks:
    """Each scoring repository replayed from `params` with the network's own online rule."""
    encode = encoded(net, SCORING, key)
    start = net.numpy_start(params)
    return {r: sequential_risks(net.rule, start, encode(r), SCORING[r]) for r in SCORING}


def cold_job(name: str, seed: int) -> dict[str, Any]:
    """The network from its own fresh start, adapting online."""
    net = net_of(name, seed)
    return {"risks": online_on_scoring(net, net.cold_params(), (name, seed))}


def maml_job(name: str, seed: int, lr: float) -> dict[str, Any]:
    """A MAML start meta-trained on the training repositories; every checkpoint replayed."""
    started, net = time.time(), net_of(name, seed)
    checkpoints = mf.meta_train(net, TRAIN, encoded(net, TRAIN, (name, seed)), lr, seed)
    torch.save(checkpoints, STARTS[0] / f"maml-{name}-{seed}-{lr:g}.pt")
    risks = {step: online_on_scoring(net, p, (name, seed)) for step, p in checkpoints}
    log.info("maml %s seed %d lr %g (%.0fs)", name, seed, lr, time.time() - started)
    return {"risks": risks}


def train_steps(net: mf.Net, key: tuple[str, int]) -> tuple[np.ndarray, np.ndarray]:
    """Every training step, encoded task by task (the fly's drive matrix would not fit), and its
    label."""
    encode = encoded(net, TRAIN, key)
    codes = np.concatenate([c for r in TRAIN for c in encode(r)])
    return codes, np.concatenate([y for r in TRAIN.values() for y in r.followed])


def broad_rows(net: mf.Net, params: mf.Params, key: tuple[str, int]) -> dict[str, Risks]:
    """Broad frozen, broad plus each fine-tune budget, and the in-domain ceiling."""
    encode, found = encoded(net, SCORING, key), {}
    found["frozen"] = {
        r: [net.frozen_prob(params, c).detach().numpy() for c in encode(r)] for r in SCORING
    }
    for steps in FINE_TUNE_STEPS:
        found[f"fine-tune {steps}"] = {
            r: mf.fine_tuned_risks(net, params, encode(r), SCORING[r].followed, steps)
            for r in SCORING
        }
    found["in-domain"] = {
        r: mf.in_domain_risks(net, params, encode(r), SCORING[r].followed, IN_DOMAIN_STEPS)
        for r in SCORING
    }
    return found


def broad_job(name: str, seed: int) -> dict[str, Any]:
    """Broad pre-training on every training step, then the fine-tune rows per epoch."""
    started, net = time.time(), net_of(name, seed)
    codes, labels = train_steps(net, (name, seed))
    checkpoints = mf.broad_fit(net, codes, labels, BROAD_EPOCHS)
    del codes
    torch.save(checkpoints, STARTS[0] / f"broad-{name}-{seed}.pt")
    risks = {epoch: broad_rows(net, p, (name, seed)) for epoch, p in checkpoints}
    log.info("broad %s seed %d (%.0fs)", name, seed, time.time() - started)
    return {"risks": risks}


def logistic_job() -> dict[str, Any]:
    """The classifier three ways: own tasks only, broad frozen, broad refit on tasks so far."""
    rows = np.vstack([x for r in TRAIN.values() for x in r.features])
    labels = np.concatenate([y for r in TRAIN.values() for y in r.followed]).astype(float)
    broad = fit_logistic(rows, labels, L2)
    own = {r: own_logistic_risks(SCORING[r]) for r in SCORING}
    return {
        "own": {r: risks for r, (risks, _) in own.items()},
        "own_silent_tasks": {r: silent for r, (_, silent) in own.items()},
        "broad": {r: [predict(broad, x) for x in SCORING[r].features] for r in SCORING},
        "refit": {
            r: refit_logistic_risks(SCORING[r], broad, FIXED[0].trouble_share) for r in SCORING
        },
    }


def run_job(job: tuple) -> tuple[tuple, dict[str, Any]]:
    """Dispatch one job in a forked worker."""
    kind, *key = job
    found = {"cold": cold_job, "maml": maml_job, "broad": broad_job, "logistic": logistic_job}[
        kind
    ](*key)
    return job, found


def all_jobs() -> list[tuple]:
    """Slowest first: the fly's MAML runs."""
    jobs: list[tuple] = []
    for name in md.NETWORKS:
        jobs += [("maml", name, s, lr) for s in (0, 1, 2) for lr in MAML_LRS]
    for name in md.NETWORKS:
        jobs += [("broad", name, s) for s in (0, 1, 2)]
        jobs += [("cold", name, s) for s in (0, 1, 2)]
    return [*jobs, ("logistic",)]


def numpy_states(net: mf.Net, start: tuple, encoded: list, repo: RepoTasks) -> list[tuple]:
    """(state, calibrator, risks) before each task, by the numpy rule."""
    state, calibrator, found = *start, []
    for codes, followed in zip(encoded, repo.followed, strict=True):
        raw = net.rule.raw(codes, state)
        found.append((state, calibrator, calibrated_task(raw, calibrator)))
        state = net.rule.learn(codes, followed, state)
        calibrator = calibrator_after(calibrator, raw, followed, META2_CALIBRATOR_RATE)
    return found


def one_task_gap(net: mf.Net, before: tuple, encoded: list, followed: list) -> float:
    """Torch from the numpy state before a task: that task's and the next task's probabilities."""
    state, calibrator, _ = before
    unroll = net.unroll
    if not net.is_fly:
        unroll = replace(unroll, start_updates=float(state.updates))
    tasks = mtorch.pad_tasks([encoded], [followed], len(encoded))
    maps = mtorch.fly_maps(net.rule.fly, [encoded], [followed], len(tasks)) if net.is_fly else None
    _, probs = unroll.run(net.params_of(state, calibrator), tasks, maps)
    return probs


def torch_matches_numpy(name: str, repos: list[str]) -> dict[str, float]:
    """Each task's rule step in torch against numpy from the same state; raises on a gap.

    Also reports, never raising, how far a free-running unroll drifts over the early window.
    """
    net, rng = net_of(name, 0), np.random.default_rng(1)
    params = [p + 0.01 * torch.from_numpy(rng.standard_normal(p.shape)) for p in net.cold_params()]
    encode, worst, drift = encoded(net, SCORING, (name, 0)), 0.0, 0.0
    for repo in repos:
        first = SCORING[repo].first(mf.EARLY_TASKS)
        codes = encode(repo)[: mf.EARLY_TASKS]
        states = numpy_states(net, net.numpy_start(params), codes, first)
        for s in range(len(states) - 1):
            probs = one_task_gap(net, states[s], codes[s : s + 2], list(first.followed[s : s + 2]))
            worst = max(worst, mtorch.check_equal(probs, [[states[s][2], states[s + 1][2]]]))
        _, free = mf.unrolled_loss(net, params, [codes], [first.followed])
        drift = max(drift, mtorch.largest_gap(free, [[st[2] for st in states]]))
    return {"one_task_max_gap": worst, "free_running_max_gap": drift}
