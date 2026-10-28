"""Meta-train where a filler starts, across repositories (T39), pure.

Violations prevented: **Paper Tiger** and **Leaky Narrative**. A start trained on the
same steps it is judged on would look good and help nobody, so each repository is one
task: the outer loop learns on training repositories, picks its step size and stopping
point on validation repositories, and is scored elsewhere. The trainer sees a filler only
through `MetaLearnable` (start, fresh state, its own local rule, the loss gradient, the
calibrated probability), so the fly and DenseNet go through the same recipe and neither
leaks its internals here.

The inner loop is the replay's own: within a repository a filler decides every step of a
session from the state it had when the session began, and learns from each step's outcome
after the session ends. First-order MAML: the gradient of the weighted loss at the start
in force for each early session is applied to the start the repository began from. Only
the readout start and calibrator move (spec 4.5); wiring and rates are the filler's.

Reptile (move toward the mean adapted start) is the second outer rule; validation picks
between them, since a long inner loop can make the first-order gradient point the wrong way.
Outer steps of first-order MAML use Adam, an optimizer of the trainer, not a filler rate. Pure: no
clock, files or environment; the run script logs and stores.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from symbiont.core.meta import (
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


class OuterStep:
    """One outer move of the start under the configured rule."""

    def __init__(self, learner: MetaLearnable, size: int, config: MetaConfig) -> None:
        """Hold the learner, the rule's step size and Adam's moments."""
        self._learner, self._config = learner, config
        self._adam = Adam.at(config.outer_rate, size)

    def __call__(self, start: MetaStart, batch: Sequence[Episode]) -> MetaStart:
        """The start after one move on `batch`."""
        cost = self._config.cost
        if self._config.rule == MetaRule.REPTILE:
            move = self._config.outer_rate * reptile_direction(self._learner, start, batch, cost)
        else:
            move, self._adam = self._adam.step(batch_gradient(self._learner, start, batch, cost))
        return start.with_vector(start.as_vector() + move)


def meta_train(
    filler: object, train: Sequence[Episode], validation: Sequence[Episode], config: MetaConfig
) -> MetaResult:
    """Outer loop over training repositories, stopped on validation repositories.

    Step 0 (the cold start) is a candidate like any other, so a meta start that never beats
    it on validation comes back as the cold start, with `best_step` 0. Raises
    NotMetaLearnableError for a filler with no start (counters), ValueError with no data.
    """
    learner = require_meta_learnable(filler)
    if not train or not validation:
        raise ValueError("meta-training needs training and validation repositories")
    rng = np.random.default_rng(config.seed)
    start = cold_start(learner)
    best, move = start, OuterStep(learner, len(start.as_vector()), config)
    curve, stale = [(0, early_loss(learner, start, validation, config.cost))], 0
    for step in range(1, config.outer_steps + 1):
        picked = rng.choice(len(train), size=min(config.batch, len(train)), replace=False)
        start = move(start, [train[i] for i in picked])
        if step % config.check_every:
            continue
        curve.append((step, early_loss(learner, start, validation, config.cost)))
        stale = 0 if curve[-1][1] < min(c[1] for c in curve[:-1]) else stale + 1
        best = start if stale == 0 else best
        if stale >= config.patience:
            break
    best_step = min(curve, key=lambda point: (point[1], point[0]))[0]
    return MetaResult(best, best_step, tuple(curve))


def cold_start(learner: MetaLearnable) -> MetaStart:
    """The filler's own fresh start: what a run with no meta-training begins from."""
    return learner.meta_start(learner.initial_state(META_RUN_SEED))


def calibrated_risks(
    probabilities: Sequence[np.ndarray], followed: Sequence[np.ndarray], cost: float
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
            calibrator = calibrator_step(calibrator, float(raw), outcome(cost, followed=label))
    return tuple(risks)
