"""META2's two techniques in torch, both on the readout and calibrator only (wiring fixed).

MAML: Adam moves the start; the inner loop is the network's own online rule unrolled over a
training repository's first tasks, so the outer gradient is exact. Broad: one fit on every
training step, frozen; a fine-tune takes a fixed few Adam steps on a new repository's tasks so
far. Checkpoints are returned; the caller selects on validation value, never on loss.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import meta2_torch as mt
import numpy as np
import torch

from symbiont.core.meta import Calibrator
from symbiont.eval.meta2_replay import FALSE_ALARM_COST, FlyRaw, with_dense_start, with_fly_start
from symbiont.eval.meta2_tasks import EARLY_TASKS

META_BATCH = 16  # training repositories per outer step
OUTER_STEPS = 200
CHECK_EVERY = 25  # outer steps between checkpoints; checkpoint 0 is the cold start
BROAD_BATCH = 2048  # training steps per broad minibatch
BROAD_LR = 1e-3
FINE_TUNE_LR = 1e-2
# DenseNet's unroll is chaotic at rate 1 (rounding grows to a whole probability in ten tasks
# [measured]), so its meta-gradient can explode; the outer step is norm-clipped.
GRAD_CLIP = 1.0
Params = list[torch.Tensor]
Encoder = Callable[[str], list[np.ndarray]]


@dataclass(frozen=True)
class Net:
    """One network at one wiring seed, as the fits see it: its rule, unroll and cold state."""

    rule: Any
    unroll: Any
    cold: Any

    @property
    def is_fly(self) -> bool:
        """The fly keeps two output sides; DenseNet one readout."""
        return isinstance(self.rule, FlyRaw)

    def cold_params(self) -> Params:
        """The network's own fresh start with the calibrator at (1, 0), as tensors."""
        if self.is_fly:
            first, second = self.cold.approach, self.cold.avoid
        else:
            first, second = self.cold.readout, np.array(self.cold.bias)
        return [torch.tensor(first), torch.tensor(second), torch.tensor(1.0), torch.tensor(0.0)]

    def numpy_start(self, params: Params) -> tuple[Any, Calibrator]:
        """The start the numpy rule replays: state and calibrator."""
        first, second, scale, bias = (p.detach().numpy() for p in params)
        if self.is_fly:
            state = with_fly_start(self.cold, first, second)
        else:
            state = with_dense_start(self.cold, first, float(second))
        return state, Calibrator(float(scale), float(bias))

    def params_of(self, state: Any, calibrator: Calibrator) -> Params:
        """The tensors of a numpy start (inverse of `numpy_start`)."""
        if self.is_fly:
            first, second = state.approach, state.avoid
        else:
            first, second = state.readout, np.array(state.bias)
        values = (first, second, np.array(calibrator.scale), np.array(calibrator.bias))
        return [torch.tensor(v, dtype=torch.float64) for v in values]

    def frozen_prob(self, params: Params, encoded: np.ndarray) -> torch.Tensor:
        """Calibrated probability of each step under frozen parameters (no online rule)."""
        if self.is_fly:
            codes = torch.from_numpy(encoded.astype(np.int64))[None]
            raw = mt.fly_raw(params[0][None], params[1][None], codes)[0]
        else:
            raw = torch.from_numpy(np.asarray(encoded, dtype=np.float64)) @ params[0] + params[1]
        return torch.sigmoid(params[2] * raw + params[3])


def unrolled_loss(net: Net, params: Params, encoded: Sequence, followed: Sequence) -> tuple:
    """Mean weighted loss per real step over the repositories' first tasks, and the probs."""
    tasks = mt.pad_tasks(encoded, followed, EARLY_TASKS)
    maps = mt.fly_maps(net.rule.fly, encoded, followed, len(tasks)) if net.is_fly else None
    loss, probs = net.unroll.run(params, tasks, maps)
    return loss / sum(t.mask.sum() for t in tasks), probs


def meta_train(net: Net, train: dict, encode: Encoder, lr: float, seed: int) -> list:
    """(outer step, params) checkpoints of a MAML start, the cold start first."""
    params = [p.clone().requires_grad_(requires_grad=True) for p in net.cold_params()]
    optimizer = torch.optim.Adam(params, lr=lr)
    rng, names = np.random.default_rng(seed), sorted(train)
    checkpoints = [(0, [p.detach().clone() for p in params])]
    for step in range(1, OUTER_STEPS + 1):
        batch = rng.choice(names, META_BATCH, replace=False)
        encoded = [encode(r)[:EARLY_TASKS] for r in batch]
        followed = [train[r].followed[:EARLY_TASKS] for r in batch]
        optimizer.zero_grad()
        loss, _ = unrolled_loss(net, params, encoded, followed)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, GRAD_CLIP)
        optimizer.step()
        if step % CHECK_EVERY == 0:
            checkpoints.append((step, [p.detach().clone() for p in params]))
    return checkpoints


def frozen_loss(net: Net, params: Params, encoded: np.ndarray, followed: np.ndarray) -> Any:
    """Mean weighted log loss (`core.meta.query_loss`) of frozen parameters on some steps."""
    prob, trouble = net.frozen_prob(params, encoded), torch.from_numpy(followed.astype(float))
    eps = 1e-12
    per_step = -trouble * torch.log(prob + eps)
    per_step = per_step - (1 - trouble) * FALSE_ALARM_COST * torch.log(1 - prob + eps)
    return per_step.mean()


def broad_fit(net: Net, encoded: np.ndarray, followed: np.ndarray, epochs: Sequence[int]) -> list:
    """(epoch, params) checkpoints of the readout and calibrator fit on every training step."""
    params = [p.clone().requires_grad_(requires_grad=True) for p in net.cold_params()]
    optimizer = torch.optim.Adam(params, lr=BROAD_LR)
    rng, found = np.random.default_rng(0), []
    for epoch in range(1, max(epochs) + 1):
        for chunk in np.array_split(rng.permutation(len(followed)), len(followed) // BROAD_BATCH):
            optimizer.zero_grad()
            frozen_loss(net, params, encoded[chunk], followed[chunk]).backward()
            optimizer.step()
        if epoch in epochs:
            found.append((epoch, [p.detach().clone() for p in params]))
    return found


def fine_tune(
    net: Net, broad: Params, encoded: np.ndarray, followed: np.ndarray, steps: int
) -> Params:
    """`steps` full-batch Adam steps from the broad weights on a repository's tasks so far."""
    params = [p.clone().requires_grad_(requires_grad=True) for p in broad]
    optimizer = torch.optim.Adam(params, lr=FINE_TUNE_LR)
    for _ in range(steps):
        optimizer.zero_grad()
        frozen_loss(net, params, encoded, followed).backward()
        optimizer.step()
    return [p.detach() for p in params]


def fine_tuned_risks(
    net: Net, broad: Params, encoded: list, followed: Sequence, steps: int
) -> list:
    """Task k+1 scored by the broad weights fine-tuned on tasks 1..k (task 1 by the broad)."""
    risks, params = [], broad
    for k, codes in enumerate(encoded):
        if k:
            seen = np.concatenate(followed[:k])
            params = fine_tune(net, broad, np.concatenate(encoded[:k]), seen, steps)
        risks.append(net.frozen_prob(params, codes).detach().numpy())
    return risks


def in_domain_risks(net: Net, broad: Params, encoded: list, followed: Sequence, steps: int) -> list:
    """Each task scored by the broad weights fine-tuned on every OTHER task of its repository.

    The in-domain ceiling: no step budget worth the name and all of the repository's own data,
    future tasks included, in five task folds. A ceiling row, never a candidate.
    """
    folds = np.arange(len(encoded)) % 5
    risks: list = [None] * len(encoded)
    for fold in np.unique(folds):
        rest = np.flatnonzero(folds != fold)
        seen = np.concatenate([followed[i] for i in rest])
        params = fine_tune(net, broad, np.concatenate([encoded[i] for i in rest]), seen, steps)
        for i in np.flatnonzero(folds == fold):
            risks[i] = net.frozen_prob(params, encoded[i]).detach().numpy()
    return risks
