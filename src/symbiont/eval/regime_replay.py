"""Two training regimes on one simulated timeline (T47, exploratory).

Violations prevented: **Paper Tiger** and **Silent Fallback**. A regime that peeks at the
session it scores would earn notes no product could; and a refit that quietly kept the old
state when it failed would score R1 under R2's name. So the timeline is fixed here, once, for
every learner: a project is processed session by session in replay order, the state that scores
session s was built only from the shipped start and sessions before s, and a refit that raises
stops the run.

- R1 live-only (spec 4.5): ship a start, then only the learner's own per-step rule on the
  project, applied after each session ends (as `offline.replay` does). A batch model that has
  no per-step rule stays frozen.
- R2 refit between sessions: after each session, `refit` builds a new state from the shipped
  start and the project's sessions so far; the next session is scored with it.

Rows are the learners' 86 features in step order. `encode` runs once per session: it depends
only on a learner's fixed input side, never on what it learned.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


@dataclass(frozen=True)
class Project:
    """One repository's sessions in replay order: (rows, followed) per session."""

    name: str
    sessions: tuple[tuple[np.ndarray, np.ndarray], ...]


class Scorer(Protocol):
    """Anything that encodes steps and scores them under a state."""

    def encode(self, rows: np.ndarray, state: Any) -> np.ndarray:
        """What the learner reads from each step; depends only on its fixed input side."""
        ...

    def step_risks(self, encoded: np.ndarray, state: Any) -> np.ndarray:
        """Risk of each encoded step under a frozen state."""
        ...


class OnlineScorer(Scorer, Protocol):
    """A scorer with its own per-step rule."""

    def initial_state(self, seed: int) -> Any:
        """A fresh state."""
        ...

    def learn(self, encoded: np.ndarray, followed: np.ndarray, state: Any) -> Any:
        """One session's outcomes, steps in order; returns a new state."""
        ...


Refit = Callable[[Sequence[np.ndarray], Sequence[np.ndarray]], Any]  # encoded, followed -> state


def train_online(scorer: OnlineScorer, projects: Sequence[Project], state: Any) -> Any:
    """The learner's own rule over every session of every project, in order."""
    for project in projects:
        for rows, followed in project.sessions:
            state = scorer.learn(scorer.encode(rows, state), followed, state)
    return state


def live_risks(scorer: OnlineScorer, project: Project, shipped: Any) -> list[np.ndarray]:
    """R1: each session scored, then learned by the per-step rule."""
    state, risks = shipped, []
    for rows, followed in project.sessions:
        encoded = scorer.encode(rows, state)
        risks.append(scorer.step_risks(encoded, state))
        state = scorer.learn(encoded, followed, state)
    return risks


def frozen_risks(scorer: Scorer, project: Project, shipped: Any) -> list[np.ndarray]:
    """R1 for a batch model: the shipped state scores every session."""
    return [
        scorer.step_risks(scorer.encode(rows, shipped), shipped) for rows, _ in project.sessions
    ]


def refit_risks(scorer: Scorer, refit: Refit, project: Project, shipped: Any) -> list[np.ndarray]:
    """R2: session s is scored by `refit` of sessions 0..s-1 (the shipped state for s = 0)."""
    encoded = [scorer.encode(rows, shipped) for rows, _ in project.sessions]
    followed = [f for _, f in project.sessions]
    state, risks = shipped, []
    for index, session in enumerate(encoded):
        risks.append(scorer.step_risks(session, state))
        if index + 1 < len(encoded):
            state = refit(encoded[: index + 1], followed[: index + 1])
    return risks


def consolidation(scorer: OnlineScorer, shipped: Any, passes: int) -> Refit:
    """R2 for an online learner: its own rule over the project so far, `passes` times."""
    if passes < 1:
        raise ValueError(f"consolidation needs at least one pass, got {passes}")

    def refit(encoded: Sequence[np.ndarray], followed: Sequence[np.ndarray]) -> Any:
        state = shipped
        for _ in range(passes):
            for session, labels in zip(encoded, followed, strict=True):
                state = scorer.learn(session, labels, state)
        return state

    return refit
