"""META2's sequential protocol: learn from a repository's tasks 1..k, score task k+1. Pure numpy.

A network decides every step of task k+1 with its state after task k, then learns the task with
its own rule and steps its calibrator through it in order; nothing is learned within a task.
The classifier rows refit after each task instead. These numpy rules are the scored ones; the
torch unroll that meta-trains a start must equal them.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

import numpy as np

from symbiont.core.dense_variants import DenseVariant, DenseVariantState
from symbiont.core.fly_variants import FlyVariant, FlyVariantState
from symbiont.core.meta import Calibrator, calibrator_step
from symbiont.core.slot import Outcome
from symbiont.eval.batch_refit import REFIT_PRIOR, LogisticScorer, map_logistic, trouble_weights
from symbiont.eval.note_cost_logistic import Logistic, fit_logistic, predict

FALSE_ALARM_COST = 0.5  # the replay's cost (T36, T46, T47): the weighted loss and the rules
# Per step, after each task; chosen on validation repositories for every T39 start (scored run).
META2_CALIBRATOR_RATE = 0.05
SILENT = -1e9  # risk of a step no model can score yet: below every threshold but `always`


@dataclass(frozen=True)
class RepoTasks:
    """One repository's tasks in issue order: per task, step features, labels and boundaries."""

    repo: str
    task_ids: tuple[str, ...]
    features: tuple[np.ndarray, ...]
    followed: tuple[np.ndarray, ...]
    boundary: tuple[np.ndarray, ...]

    def __post_init__(self) -> None:
        """Refuse tasks whose columns do not line up."""
        sizes = {len(self.task_ids), len(self.features), len(self.followed), len(self.boundary)}
        if len(sizes) != 1:
            raise ValueError(f"{self.repo}: task columns of different lengths {sorted(sizes)}")
        for x, y, b in zip(self.features, self.followed, self.boundary, strict=True):
            if not len(x) == len(y) == len(b):
                raise ValueError(f"{self.repo}: a task with {len(x)}, {len(y)}, {len(b)} steps")

    def first(self, tasks: int) -> "RepoTasks":
        """The repository's first `tasks` tasks."""
        return RepoTasks(
            self.repo,
            self.task_ids[:tasks],
            self.features[:tasks],
            self.followed[:tasks],
            self.boundary[:tasks],
        )


class RawRule(Protocol):
    """A network seen as a raw score per step and a local rule over a task's outcomes."""

    def encode(self, rows: np.ndarray, state: Any) -> np.ndarray:
        """What the readout sees for each step."""
        ...

    def raw(self, encoded: np.ndarray, state: Any) -> np.ndarray:
        """The uncalibrated score of each step under a frozen state."""
        ...

    def learn(self, encoded: np.ndarray, followed: np.ndarray, state: Any) -> Any:
        """The network's own rule over one task's steps, in order."""
        ...


@dataclass(frozen=True)
class FlyRaw:
    """The fly variant; its raw score is avoid minus approach output (the T48 fly combined)."""

    fly: FlyVariant

    def encode(self, rows: np.ndarray, state: FlyVariantState) -> np.ndarray:
        """Kenyon cell indices of each step."""
        return self.fly.encode(rows, state)

    def raw(self, encoded: np.ndarray, state: FlyVariantState) -> np.ndarray:
        """Avoid minus approach, the fly's own risk."""
        return self.fly.step_risks(encoded, state)

    def learn(self, encoded: np.ndarray, followed: np.ndarray, state: FlyVariantState) -> Any:
        """The dopamine rule."""
        return self.fly.learn(encoded, followed, state)


@dataclass(frozen=True)
class DenseRaw:
    """The DenseNet variant; its raw score is the readout's logit."""

    dense: DenseVariant

    def encode(self, rows: np.ndarray, state: DenseVariantState) -> np.ndarray:
        """Hidden activity and any skip inputs."""
        return self.dense.encode(rows, state)

    def raw(self, encoded: np.ndarray, state: DenseVariantState) -> np.ndarray:
        """The readout logit; DenseNet's own probability is its sigmoid."""
        logit: np.ndarray = encoded @ state.readout + state.bias
        return logit

    def learn(self, encoded: np.ndarray, followed: np.ndarray, state: DenseVariantState) -> Any:
        """The delta rule."""
        return self.dense.learn(encoded, followed, state)


def calibrated_task(raw: np.ndarray, calibrator: Calibrator) -> np.ndarray:
    """Probabilities of one task's steps under the calibrator in force."""
    return np.array([calibrator.probability(float(r)) for r in raw])


def calibrator_after(
    calibrator: Calibrator, raw: np.ndarray, followed: np.ndarray, rate: float
) -> Calibrator:
    """The calibrator stepped through one task's outcomes in order."""
    for score, trouble in zip(raw, followed, strict=True):
        outcome = Outcome(bool(trouble), None, false_alarm_cost=FALSE_ALARM_COST)
        calibrator = calibrator_step(calibrator, float(score), outcome, rate)
    return calibrator


def sequential_risks(
    rule: RawRule,
    start: tuple[Any, Calibrator],
    encoded: Sequence[np.ndarray],
    repo: RepoTasks,
    rate: float = META2_CALIBRATOR_RATE,
) -> list[np.ndarray]:
    """Each task decided from the state after the tasks before it; `encoded` is per task."""
    state, calibrator = start
    risks = []
    for codes, followed in zip(encoded, repo.followed, strict=True):
        raw = rule.raw(codes, state)
        risks.append(calibrated_task(raw, calibrator))
        state = rule.learn(codes, followed, state)
        calibrator = calibrator_after(calibrator, raw, followed, rate)
    return risks


def with_fly_start(state: FlyVariantState, approach: np.ndarray, avoid: np.ndarray) -> Any:
    """The fly's fixed wiring with these output weights."""
    return replace(state, approach=approach.copy(), avoid=avoid.copy())


def with_dense_start(state: DenseVariantState, readout: np.ndarray, bias: float) -> Any:
    """DenseNet's fixed hidden layer with this readout."""
    return replace(state, readout=readout.copy(), bias=float(bias))


L2 = 1000.0  # the live classifier's penalty (T46 curve, T48)


def own_logistic_risks(repo: RepoTasks, l2: float = L2) -> tuple[list[np.ndarray], int]:
    """Task k+1 scored by a classifier fit on tasks 1..k only; silent until both labels occur.

    Returns the risks and how many tasks were silent for want of a fit.
    """
    risks, silent = [], 0
    for k, rows in enumerate(repo.features):
        seen = np.concatenate(repo.followed[:k]) if k else np.zeros(0, dtype=bool)
        if not 0 < seen.sum() < len(seen):
            risks.append(np.full(len(rows), SILENT))
            silent += 1
            continue
        model = fit_logistic(np.vstack(repo.features[:k]), seen.astype(float), l2)
        risks.append(predict(model, rows))
    return risks, silent


def refit_logistic_risks(repo: RepoTasks, broad: Logistic, share: float) -> list[np.ndarray]:
    """Task k+1 scored by the broad classifier refit on tasks 1..k toward its own coefficients.

    The live warner's adapting form (T39, T47 R2): standardization fixed by the broad fit,
    class weights by the training trouble share, prior strength `REFIT_PRIOR`.
    """
    risks, coef, scorer = [], broad.coef, LogisticScorer(broad)
    for k, rows in enumerate(repo.features):
        if k:
            seen = np.concatenate(repo.followed[:k])
            design = scorer.encode(np.vstack(repo.features[:k]), coef)
            weights = trouble_weights(seen, share)
            coef = map_logistic(design, seen.astype(float), weights, broad.coef, REFIT_PRIOR)
        risks.append(predict(replace(broad, coef=coef), rows))
    return risks
