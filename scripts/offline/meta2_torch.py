"""META2's differentiable inner loop: the fly's and DenseNet's own online rules, in torch.

Over a padded meta-batch of repositories' first tasks, each task is decided from the state after
the tasks before it, then learned by the network's rule and the calibrator, exactly as
`meta2_replay.sequential_risks`. Only the start (readout, calibrator) is a parameter; wiring and
rates are fixed. `check_equal` refuses to go on unless the unroll reproduces the numpy rule.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import torch

from symbiont.core.dense_variants import DenseVariant
from symbiont.core.fly_variants import FlyVariant
from symbiont.core.mushroom import N_KC
from symbiont.eval.meta2_fly_map import task_map
from symbiont.eval.meta2_replay import FALSE_ALARM_COST

torch.set_default_dtype(torch.float64)
# Checked one task at a time from the numpy state (teacher forcing): run free, DenseNet's delta
# rule at rate 1 grows summation-order rounding (1e-16) to a whole probability within ten tasks.
EQUAL_TOLERANCE = 1e-9
Pair = tuple[torch.Tensor, torch.Tensor]


@dataclass(frozen=True)
class Task:
    """One task index across a meta-batch: (repos, steps, ...) encodings, labels, real steps."""

    encoded: torch.Tensor
    followed: torch.Tensor
    mask: torch.Tensor


def _padded_task(here: list, width: int) -> Task:
    """Zero-padded arrays of one task index; `None` marks a repository without that task."""
    first = next(h for h in here if h is not None)
    enc = np.zeros((len(here), width, *first[0].shape[1:]), dtype=first[0].dtype)
    lab, mask = np.zeros((len(here), width)), np.zeros((len(here), width))
    for i, h in enumerate(here):
        if h is not None:
            steps = len(h[1])
            enc[i, :steps], lab[i, :steps], mask[i, :steps] = h[0], h[1], 1.0
    return Task(torch.from_numpy(enc), torch.from_numpy(lab), torch.from_numpy(mask))


def pad_tasks(
    encoded: Sequence[Sequence[np.ndarray]], followed: Sequence[Sequence[np.ndarray]], tasks: int
) -> list[Task]:
    """Repositories' first `tasks` tasks, zero-padded; a missing task is all padding."""
    found = []
    for s in range(tasks):
        here = [
            (e[s], f[s]) if s < len(e) else None for e, f in zip(encoded, followed, strict=True)
        ]
        if all(h is None for h in here):
            break
        found.append(_padded_task(here, max(len(h[1]) for h in here if h is not None)))
    return found


def weighted_loss(prob: torch.Tensor, task: Task) -> torch.Tensor:
    """Summed false-alarm-weighted log loss (`core.meta.query_loss`) over real steps."""
    eps = 1e-12
    per_step = -task.followed * torch.log(prob + eps)
    per_step = per_step - (1 - task.followed) * FALSE_ALARM_COST * torch.log(1 - prob + eps)
    return (per_step * task.mask).sum()


def calibrator_through(calibrator: Pair, raw: torch.Tensor, task: Task, rate: float) -> Pair:
    """`meta2_replay.calibrator_after` for every repository at once, step by step."""
    scale, bias = calibrator
    for t in range(raw.shape[1]):
        prob = torch.sigmoid(scale * raw[:, t] + bias)
        trouble = task.followed[:, t] > 0
        dz = torch.where(trouble, -(1 - prob), FALSE_ALARM_COST * prob) * task.mask[:, t]
        scale, bias = scale - rate * dz * raw[:, t], bias - rate * dz
    return scale, bias


def fly_maps(fly: FlyVariant, codes: Sequence, followed: Sequence, tasks: int) -> list:
    """Per task index, (repos, 4, compartments, N_KC): approach and avoid scale and shift."""
    ones = np.ones((len(fly.rates), N_KC))
    identity = np.stack([ones, 0 * ones, ones, 0 * ones])
    found = []
    for s in range(tasks):
        per_repo = []
        for c, f in zip(codes, followed, strict=True):
            if s >= len(c):
                per_repo.append(identity)
                continue
            mapped = task_map(fly, c[s], f[s])
            sides = (mapped.approach, mapped.avoid)
            per_repo.append(np.stack([part for side in sides for part in (side.scale, side.shift)]))
        found.append(torch.from_numpy(np.stack(per_repo)))
    return found


def fly_raw(approach: torch.Tensor, avoid: torch.Tensor, codes: torch.Tensor) -> torch.Tensor:
    """(repos, steps) avoid minus approach output, as `FlyVariant.step_risks`."""
    repos, steps, active = codes.shape
    index = codes.reshape(repos, 1, steps * active).expand(-1, approach.shape[1], -1)

    def mean_of(weights: torch.Tensor) -> torch.Tensor:
        picked = torch.gather(weights, 2, index).reshape(repos, -1, steps, active)
        return picked.mean(3).mean(1)

    return mean_of(avoid) - mean_of(approach)


@dataclass(frozen=True)
class FlyUnroll:
    """The fly's start (approach, avoid, scale, bias) through its dopamine rule over tasks."""

    calibrator_rate: float

    def run(self, start: Sequence[torch.Tensor], tasks: list[Task], maps: list) -> tuple:
        """Summed loss and the probabilities of every task; `maps` from `fly_maps`."""
        repos = tasks[0].mask.shape[0]
        approach, avoid = start[0].expand(repos, -1, -1), start[1].expand(repos, -1, -1)
        calibrator = (start[2].expand(repos), start[3].expand(repos))
        loss, probs = torch.zeros(()), []
        for task, m in zip(tasks, maps, strict=True):
            raw = fly_raw(approach, avoid, task.encoded.long())
            prob = torch.sigmoid(calibrator[0][:, None] * raw + calibrator[1][:, None])
            loss = loss + weighted_loss(prob, task)
            probs.append(prob)
            approach, avoid = m[:, 0] * approach + m[:, 1], m[:, 2] * avoid + m[:, 3]
            calibrator = calibrator_through(calibrator, raw, task, self.calibrator_rate)
        return loss, probs


@dataclass(frozen=True)
class DenseUnroll:
    """DenseNet's start (readout, bias, scale, bias) through its delta rule over tasks."""

    dense: DenseVariant
    calibrator_rate: float
    start_updates: float = 0.0  # a fresh state has learned nothing; the check starts mid-repo

    def rate_at(self, updates: torch.Tensor) -> torch.Tensor | float:
        """`DenseVariant.rate_at` per repository."""
        if self.dense.rate_halflife is None:
            return self.dense.rate
        return self.dense.rate / (1.0 + updates / self.dense.rate_halflife)

    def learn(self, readout: Pair, updates: torch.Tensor, task: Task) -> tuple:
        """`DenseVariant.learn` over one task for every repository at once."""
        weights, bias = readout
        weight = torch.where(task.followed > 0, self.dense.trouble_weight, 1.0)
        for t in range(task.encoded.shape[1]):
            phi = task.encoded[:, t]
            logit = torch.clamp((phi * weights).sum(1) + bias, -30.0, 30.0)
            error = torch.sigmoid(logit) - task.followed[:, t]
            step = self.rate_at(updates) * error * weight[:, t] * task.mask[:, t]
            weights, bias = weights - step[:, None] * phi, bias - step
            updates = updates + task.mask[:, t]
        return (weights, bias), updates

    def run(self, start: Sequence[torch.Tensor], tasks: list[Task], maps: object = None) -> tuple:
        """Summed loss and the probabilities of every task."""
        repos = tasks[0].mask.shape[0]
        readout = (start[0].expand(repos, -1), start[1].expand(repos))
        calibrator = (start[2].expand(repos), start[3].expand(repos))
        updates, loss = torch.full((repos,), self.start_updates), torch.zeros(())
        probs = []
        for task in tasks:
            raw = (task.encoded * readout[0][:, None, :]).sum(2) + readout[1][:, None]
            prob = torch.sigmoid(calibrator[0][:, None] * raw + calibrator[1][:, None])
            loss = loss + weighted_loss(prob, task)
            probs.append(prob)
            readout, updates = self.learn(readout, updates, task)
            calibrator = calibrator_through(calibrator, raw, task, self.calibrator_rate)
        return loss, probs


def check_equal(probs: list[torch.Tensor], numpy_risks: Sequence[Sequence[np.ndarray]]) -> float:
    """Largest gap between the unroll and the numpy rule; raises above `EQUAL_TOLERANCE`."""
    gap = largest_gap(probs, numpy_risks)
    if gap > EQUAL_TOLERANCE:
        raise RuntimeError(f"the torch unroll differs from the numpy rule by {gap:g}")
    return gap


def largest_gap(probs: list[torch.Tensor], numpy_risks: Sequence[Sequence[np.ndarray]]) -> float:
    """Largest absolute gap between unrolled probabilities and the numpy rule's."""
    gap = 0.0
    for s, prob in enumerate(probs):
        for i, risks in enumerate(numpy_risks):
            if s < len(risks):
                found = prob[i, : len(risks[s])].detach().numpy()
                gap = max(gap, float(np.max(np.abs(found - risks[s]))))
    return gap
