"""META2 episodes as `RepoTasks`, and the two networks under test, fixed by training data only.

The fly is T48's "fly combined" (gain control, fast and slow compartments, approach and avoid
outputs); DenseNet is T48's "DenseNet combined" readout (512 fixed tanh units at fan-in scale,
a skip from the gained inputs, rate 1 decaying, balanced trouble weight). Input gain and the
trouble share come from the training repositories, never validation or held-out ones.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from fly_ablation_arms import DECAY_HALFLIFE, FAN_IN, SLOW_RATE, WIDE

from symbiont.core.dense_variants import DenseVariant, ReadoutInput
from symbiont.core.fly_variants import FlyVariant, Valence
from symbiont.core.input_gain import InputGain, fit_input_gain
from symbiont.eval.meta2_replay import DenseRaw, FlyRaw, RepoTasks

FLY, DENSE = "fly combined", "DenseNet combined"
NETWORKS = (FLY, DENSE)


def load_role(path: Path) -> tuple[dict[str, RepoTasks], dict[str, list[np.ndarray]]]:
    """One role's episodes (`meta2_episodes.py build`) and the counters' risks, by repository."""
    stored = np.load(path)
    found, counters = {}, {}
    for index, repo in enumerate(stored["repos"].tolist()):
        cuts = np.cumsum(stored[f"{index}.n"])[:-1]

        def split(key: str, cuts: np.ndarray = cuts, at: int = index) -> tuple[np.ndarray, ...]:
            return tuple(np.split(stored[f"{at}.{key}"], cuts))

        tasks = tuple(stored[f"{index}.t"].tolist())
        found[repo] = RepoTasks(repo, tasks, split("x"), split("y"), split("b"))
        counters[repo] = list(split("c"))
    return found, counters


@dataclass(frozen=True)
class Fixed:
    """What the training repositories fix: input gain and trouble share."""

    gain: InputGain
    trouble_share: float


def fixed_from(train: dict[str, RepoTasks]) -> Fixed:
    """Input gain and trouble share of every training step."""
    rows = np.vstack([x for r in train.values() for x in r.features])
    labels = np.concatenate([y for r in train.values() for y in r.followed])
    return Fixed(fit_input_gain(rows), float(labels.mean()))


def network(name: str, seed: int, fixed: Fixed) -> Any:
    """The raw-score rule of one network at one wiring seed."""
    if name == FLY:
        return FlyRaw(
            FlyVariant(seed, gain=fixed.gain, rates=(0.1, SLOW_RATE), valence=Valence.TWO_VALENCE)
        )
    balance = (1 - fixed.trouble_share) / fixed.trouble_share
    return DenseRaw(
        DenseVariant(
            seed,
            hidden=WIDE,
            rate=1.0,
            rate_halflife=DECAY_HALFLIFE,
            trouble_weight=balance,
            readout_input=ReadoutInput.HIDDEN_AND_INPUTS,
            gain=fixed.gain,
            hidden_scale=FAN_IN,
        )
    )


def cold_state(rule: Any) -> Any:
    """The network's own fresh state (weights 1 for the fly, readout 0 for DenseNet)."""
    inner = rule.fly if isinstance(rule, FlyRaw) else rule.dense
    return inner.initial_state(0)


def encode_all(rule: Any, repos: dict[str, RepoTasks]) -> dict[str, list[np.ndarray]]:
    """Every task's encoding: Kenyon cell indices (int16) or readout inputs."""
    state = cold_state(rule)
    found = {}
    for name, repo in repos.items():
        codes = [rule.encode(x, state) for x in repo.features]
        found[name] = [c.astype(np.int16) if isinstance(rule, FlyRaw) else c for c in codes]
    return found
