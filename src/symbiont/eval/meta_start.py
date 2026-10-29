"""Meta-train where a filler starts, across repositories (T39), pure.

Each repository is one task: the outer loop learns on training repositories, picks its step size
and stopping point on validation repositories, and is scored elsewhere. The trainer sees a filler
only through `MetaLearnable`. First-order MAML (Adam outer steps) or Reptile; validation picks.
Within a repository a filler learns from a session's outcomes after the session ends.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

import numpy as np

from symbiont.core.meta import (
    CALIBRATOR_RATE,
    META_RUN_SEED,
    Calibrator,
    MetaLearnable,
    MetaStart,
    calibrator_step,
    require_meta_learnable,
)
from symbiont.core.slot import Outcome
from symbiont.eval.repo_pool import EXCLUDED, HELD_OUT

# Spec 4.5: the first ~10 outcomes on a new repository are scored on their own. Learning
# happens when a session ends, so a repository's first outcomes arrive session by session;
# the window is its first 10 sessions (prereg 2026-10-28 meta-start, section "Windows").
EARLY_SESSIONS = 10
_EPS = 1e-12
SCORING_FOLD = 0  # the pool fold T46 scored its repository curve on; T39 scores there too
VALIDATION_REPOS = 10  # of the 80 training repositories: early stopping and outer step size
SPLIT_SEED = 20261028


@dataclass(frozen=True)
class MetaSplit:
    """Which pool repositories train the start, stop it, and score it."""

    train: tuple[str, ...]
    validation: tuple[str, ...]
    scoring: tuple[str, ...]


def meta_split(pool: Sequence[dict[str, object]]) -> MetaSplit:
    """Scoring is the pool's scoring fold; a seeded 10 of the rest validate; the rest train.

    Raises if a held-out or excluded repository is in the pool: they are never read here.
    """
    names = [str(entry["repo"]) for entry in pool]
    blocked = sorted(set(names) & (set(HELD_OUT) | set(EXCLUDED)))
    if blocked:
        raise ValueError(f"held-out or excluded repositories in the pool: {blocked}")
    scoring = tuple(str(e["repo"]) for e in pool if e["fold"] == SCORING_FOLD)
    rest = sorted(set(names) - set(scoring))
    validation = sorted(
        np.random.default_rng(SPLIT_SEED).choice(rest, VALIDATION_REPOS, replace=False)
    )
    train = tuple(r for r in rest if r not in validation)
    return MetaSplit(train, tuple(map(str, validation)), scoring)


@dataclass(frozen=True)
class Episode:
    """One repository in replay order: per session, step features and labels."""

    repo: str
    features: tuple[np.ndarray, ...]  # (steps, features) per session
    followed: tuple[np.ndarray, ...]  # bool per step

    def __post_init__(self) -> None:
        """Refuse sessions whose features and labels do not line up."""
        if len(self.features) != len(self.followed):
            raise ValueError(f"{self.repo}: {len(self.features)} sessions of features")
        for x, y in zip(self.features, self.followed, strict=True):
            if len(x) != len(y):
                raise ValueError(f"{self.repo}: {len(x)} feature rows for {len(y)} labels")

    def early(self, sessions: int = EARLY_SESSIONS) -> "Episode":
        """The repository's first `sessions` sessions."""
        return Episode(self.repo, self.features[:sessions], self.followed[:sessions])


def outcome(cost: float, *, followed: bool) -> Outcome:
    """What the replay teaches a filler after one step (the kind of trouble is not needed)."""
    return Outcome(bool(followed), None, false_alarm_cost=1.0 if followed else cost)


def weighted_log_loss(probability: np.ndarray, followed: np.ndarray, cost: float) -> np.ndarray:
    """Per-step loss in which a false alarm costs `cost` misses (as `core.meta.query_loss`)."""
    clipped = np.clip(probability, _EPS, 1 - _EPS)
    loss: np.ndarray = np.where(followed, -np.log(clipped), -cost * np.log(1 - clipped))
    return loss


def adapt(
    filler: MetaLearnable, start: MetaStart, x: np.ndarray, y: np.ndarray, cost: float
) -> MetaStart:
    """The start after the filler's own rule has learned one session, step by step."""
    for features, followed in zip(x, y, strict=True):
        start = filler.inner_step(start, features, outcome(cost, followed=followed))
    return start


def online_risks(
    filler: MetaLearnable, start: MetaStart, episode: Episode, cost: float
) -> tuple[np.ndarray, ...]:
    """Calibrated trouble probability at every step, adapting online from `start`."""
    risks = []
    for x, y in zip(episode.features, episode.followed, strict=True):
        state = filler.fresh_state(start)
        risks.append(np.array([filler.trouble_probability(row, state) for row in x]))
        start = adapt(filler, start, x, y, cost)
    return tuple(risks)


def early_loss(
    filler: MetaLearnable, start: MetaStart, episodes: Sequence[Episode], cost: float
) -> float:
    """Mean weighted loss per step over each repository's early window, adapting online."""
    losses = [
        weighted_log_loss(r, y, cost)
        for e in episodes
        for r, y in zip(
            online_risks(filler, start, e.early(), cost), e.early().followed, strict=True
        )
    ]
    return float(np.concatenate(losses).mean())


def early_gradient(
    filler: MetaLearnable, start: MetaStart, episode: Episode, cost: float
) -> tuple[np.ndarray, int]:
    """First-order meta-gradient (summed over steps) of one repository's early window."""
    total, steps, adapted = np.zeros_like(start.as_vector()), 0, start
    for x, y in zip(episode.early().features, episode.early().followed, strict=True):
        for features, followed in zip(x, y, strict=True):
            taught = outcome(cost, followed=followed)
            total += filler.query_gradient(adapted, features, taught).as_vector()
        steps += len(y)
        adapted = adapt(filler, adapted, x, y, cost)
    return total, steps


@dataclass(frozen=True)
class Adam:
    """The outer loop's optimizer state; `step` returns the move and the next state."""

    rate: float
    first: np.ndarray
    second: np.ndarray
    count: int = 0

    @classmethod
    def at(cls, rate: float, size: int) -> "Adam":
        """Fresh moments for a parameter vector of `size`."""
        return cls(rate, np.zeros(size), np.zeros(size))

    def step(self, gradient: np.ndarray) -> tuple[np.ndarray, "Adam"]:
        """The parameter change for `gradient` (standard Adam constants)."""
        count = self.count + 1
        first = 0.9 * self.first + 0.1 * gradient
        second = 0.999 * self.second + 0.001 * gradient**2
        unbiased = first / (1 - 0.9**count)
        scale = np.sqrt(second / (1 - 0.999**count)) + 1e-8
        return -self.rate * unbiased / scale, Adam(self.rate, first, second, count)


class MetaRule(StrEnum):
    """How the outer loop moves the start; both are first-order, chosen on validation."""

    # Adam on the loss gradient at the start in force for each early session.
    FIRST_ORDER_MAML = "first-order MAML"
    # A fraction `outer_rate` of the way toward the batch's mean adapted start.
    REPTILE = "Reptile"


@dataclass(frozen=True)
class MetaConfig:
    """How long and how hard the outer loop runs; fixed in the prereg."""

    outer_rate: float
    rule: MetaRule = MetaRule.FIRST_ORDER_MAML
    outer_steps: int = 300
    batch: int = 8  # repositories per outer step
    check_every: int = 20  # outer steps between validation checks
    patience: int = 5  # checks without a better validation loss before stopping
    seed: int = 0
    cost: float = 0.5  # false-alarm cost the fillers learn with (T36/T46 c)


@dataclass(frozen=True)
class MetaResult:
    """The best start found, when, and the validation curve that chose it."""

    start: MetaStart
    best_step: int
    curve: tuple[tuple[int, float], ...] = field(default=())

    @property
    def best_loss(self) -> float:
        """Validation loss of the returned start."""
        return dict(self.curve)[self.best_step]


def batch_gradient(
    filler: MetaLearnable, start: MetaStart, batch: Sequence[Episode], cost: float
) -> np.ndarray:
    """Mean first-order meta-gradient per step over a batch of repositories."""
    parts = [early_gradient(filler, start, episode, cost) for episode in batch]
    total: np.ndarray = np.sum([g for g, _ in parts], axis=0)
    return total / max(1, sum(n for _, n in parts))


def adapted_end(
    filler: MetaLearnable, start: MetaStart, episode: Episode, cost: float
) -> MetaStart:
    """Where the filler's own rule has taken `start` after the repository's early window."""
    for x, y in zip(episode.early().features, episode.early().followed, strict=True):
        start = adapt(filler, start, x, y, cost)
    return start


def reptile_direction(
    filler: MetaLearnable, start: MetaStart, batch: Sequence[Episode], cost: float
) -> np.ndarray:
    """Mean adapted start minus the start, over a batch of repositories."""
    ends = [adapted_end(filler, start, episode, cost).as_vector() for episode in batch]
    direction: np.ndarray = np.mean(ends, axis=0) - start.as_vector()
    return direction


def outer_move(
    learner: MetaLearnable, config: MetaConfig, progress: "MetaProgress", batch: Sequence[Episode]
) -> tuple[MetaStart, Adam]:
    """The start (and Adam's moments) after one outer move on `batch`."""
    start, cost = progress.start, config.cost
    if config.rule == MetaRule.REPTILE:
        move = config.outer_rate * reptile_direction(learner, start, batch, cost)
        return start.with_vector(start.as_vector() + move), progress.adam
    move, adam = progress.adam.step(batch_gradient(learner, start, batch, cost))
    return start.with_vector(start.as_vector() + move), adam


@dataclass(frozen=True)
class MetaProgress:
    """Everything the outer loop needs to resume exactly where a check left it."""

    step: int
    start: MetaStart
    best: MetaStart
    curve: tuple[tuple[int, float], ...]
    stale: int
    adam: Adam
    rng_state: dict[str, Any]

    def finished(self, config: MetaConfig) -> bool:
        """Out of outer steps, or out of patience."""
        return self.step >= config.outer_steps or self.stale >= config.patience

    def result(self) -> MetaResult:
        """The best start so far and the curve that chose it."""
        best_step = min(self.curve, key=lambda point: (point[1], point[0]))[0]
        return MetaResult(self.best, best_step, self.curve)


def first_progress(
    learner: MetaLearnable, validation: Sequence[Episode], config: MetaConfig
) -> MetaProgress:
    """Step 0: the cold start, its validation loss, fresh Adam and the seeded sampler."""
    start = cold_start(learner)
    loss = early_loss(learner, start, validation, config.cost)
    adam = Adam.at(config.outer_rate, len(start.as_vector()))
    rng_state = dict(np.random.default_rng(config.seed).bit_generator.state)
    return MetaProgress(0, start, start, ((0, loss),), 0, adam, rng_state)


def checked(progress: MetaProgress, start: MetaStart, loss: float) -> MetaProgress:
    """Progress after a validation check of `start`."""
    better = loss < min(point[1] for point in progress.curve)
    return replace(
        progress,
        start=start,
        best=start if better else progress.best,
        curve=(*progress.curve, (progress.step, loss)),
        stale=0 if better else progress.stale + 1,
    )


def train_until_check(
    learner: MetaLearnable,
    episodes: tuple[Sequence[Episode], Sequence[Episode]],
    config: MetaConfig,
    progress: MetaProgress,
) -> MetaProgress:
    """Outer steps up to the next validation check (or the last step), then the check."""
    train, validation = episodes
    rng = np.random.default_rng()
    rng.bit_generator.state = progress.rng_state
    while True:
        picked = rng.choice(len(train), size=min(config.batch, len(train)), replace=False)
        start, adam = outer_move(learner, config, progress, [train[i] for i in picked])
        progress = replace(progress, step=progress.step + 1, start=start, adam=adam)
        if progress.step % config.check_every == 0 or progress.step >= config.outer_steps:
            break
    progress = replace(progress, rng_state=dict(rng.bit_generator.state))
    return checked(
        progress, progress.start, early_loss(learner, progress.start, validation, config.cost)
    )


@dataclass(frozen=True)
class Checkpoints:
    """Where a meta-training run resumes from, and who is told at each validation check."""

    resume: MetaProgress | None = None
    on_check: Callable[[MetaProgress], None] | None = None


def meta_train(
    filler: object,
    train: Sequence[Episode],
    validation: Sequence[Episode],
    config: MetaConfig,
    checkpoints: "Checkpoints | None" = None,
) -> MetaResult:
    """Outer loop over training repositories, stopped on validation (cold start is a candidate)."""
    learner = require_meta_learnable(filler)
    if not train or not validation:
        raise ValueError("meta-training needs training and validation repositories")
    hooks = checkpoints or Checkpoints()
    progress = hooks.resume or first_progress(learner, validation, config)
    while not progress.finished(config):
        progress = train_until_check(learner, (train, validation), config, progress)
        if hooks.on_check is not None:
            hooks.on_check(progress)
    return progress.result()


def cold_start(learner: MetaLearnable) -> MetaStart:
    """The filler's own fresh start: what a run with no meta-training begins from."""
    return learner.meta_start(learner.initial_state(META_RUN_SEED))


def calibrated_risks(
    probabilities: Sequence[np.ndarray],
    followed: Sequence[np.ndarray],
    cost: float,
    rate: float = CALIBRATOR_RATE,
) -> tuple[np.ndarray, ...]:
    """A fixed classifier's probabilities through the fillers' online calibrator.

    The calibrator starts at identity on the classifier's logit and learns from each outcome
    after its session ends, exactly as the meta-started fillers' calibrators do.
    """
    calibrator, risks = Calibrator(), []
    for p, y in zip(probabilities, followed, strict=True):
        logit = np.log(np.clip(p, _EPS, 1 - _EPS)) - np.log(np.clip(1 - p, _EPS, 1 - _EPS))
        risks.append(np.array([calibrator.probability(raw) for raw in logit]))
        for raw, label in zip(logit, y, strict=True):
            calibrator = calibrator_step(
                calibrator, float(raw), outcome(cost, followed=label), rate
            )
    return tuple(risks)
