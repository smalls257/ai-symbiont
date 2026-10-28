"""A one-hidden-layer tanh network trained by backprop: the T47 ceiling probe and R2 refits.

Violation prevented: **Paper Tiger**. If no network trained by backprop on the 86 features beats
the batch logistic regression, the classifier's lead is the ceiling of these features and no
fly or DenseNet fix can pass it; if one does, there is nonlinear signal a filler could still
reach. This is a reference row, never a candidate filler: spec 4.5 forbids learned input
wiring for fillers. The same network, started from a DenseNet variant's fixed layer, is the R2
"refit the hidden layer too" variant.

The network: gained inputs x, hidden tanh(w_in x + b_in), risk sigmoid(w_out . hidden +
w_skip . x + bias). The skip makes it at least a logistic regression. Loss: class-weighted log
loss; Adam steps. Pure numpy, deterministic given the seed.
"""

from dataclasses import dataclass, replace

import numpy as np

from symbiont.core.input_gain import InputGain, fit_input_gain
from symbiont.eval.note_cost_logistic import class_weights

MLP_HIDDEN = 64  # a small layer: the probe asks whether any nonlinearity helps, not how much
BATCH = 512
EPOCHS = 30
PATIENCE = 3  # epochs without a better validation loss before stopping
ADAM_RATE = 1e-3
FINE_TUNE_RATE = 1e-2
FINE_TUNE_STEPS = 20


@dataclass(frozen=True)
class TanhNet:
    """Weights of the network and the fixed gain in front of it."""

    gain: InputGain
    w_in: np.ndarray  # (hidden, inputs)
    b_in: np.ndarray  # (hidden,)
    w_out: np.ndarray  # (hidden,)
    w_skip: np.ndarray  # (inputs,)
    bias: float

    def as_vector(self) -> np.ndarray:
        """Every trained weight, flat."""
        return np.concatenate([self.w_in.ravel(), self.b_in, self.w_out, self.w_skip, [self.bias]])

    def with_vector(self, vector: np.ndarray) -> "TanhNet":
        """The same network with the flat weights `vector`."""
        sizes = np.cumsum([self.w_in.size, len(self.b_in), len(self.w_out), len(self.w_skip)])
        w_in, b_in, w_out, w_skip, bias = np.split(vector, sizes)
        return replace(
            self,
            w_in=w_in.reshape(self.w_in.shape),
            b_in=b_in,
            w_out=w_out,
            w_skip=w_skip,
            bias=float(bias[0]),
        )


class NetScorer:
    """The network as a `regime_replay.Scorer`: the state is the network."""

    def encode(self, rows: np.ndarray, net: TanhNet) -> np.ndarray:
        """Inputs after the network's gain."""
        return net.gain.apply(np.atleast_2d(rows))

    def step_risks(self, encoded: np.ndarray, net: TanhNet) -> np.ndarray:
        """Probability of trouble for each step."""
        return _forward(net, encoded)[1]


def _forward(net: TanhNet, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hidden = np.tanh(x @ net.w_in.T + net.b_in)
    logit = hidden @ net.w_out + x @ net.w_skip + net.bias
    return hidden, 1.0 / (1.0 + np.exp(-np.clip(logit, -30.0, 30.0)))


def gradient(net: TanhNet, x: np.ndarray, labels: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Gradient of the summed weighted log loss, flat in `as_vector` order."""
    hidden, risk = _forward(net, x)
    dz = weights * (risk - labels)
    dhidden = np.outer(dz, net.w_out) * (1.0 - hidden**2)
    parts = [dhidden.T @ x, dhidden.sum(axis=0), hidden.T @ dz, x.T @ dz, [dz.sum()]]
    return np.concatenate([np.ravel(p) for p in parts])


def weighted_loss(net: TanhNet, x: np.ndarray, labels: np.ndarray, weights: np.ndarray) -> float:
    """Mean weighted log loss."""
    risk = np.clip(_forward(net, x)[1], 1e-12, 1 - 1e-12)
    return float(np.mean(-weights * np.where(labels, np.log(risk), np.log(1 - risk))))


class _Adam:
    def __init__(self, size: int, rate: float) -> None:
        self.rate, self.t = rate, 0
        self.m, self.v = np.zeros(size), np.zeros(size)

    def step(self, vector: np.ndarray, grad: np.ndarray) -> np.ndarray:
        self.t += 1
        self.m = 0.9 * self.m + 0.1 * grad
        self.v = 0.999 * self.v + 0.001 * grad**2
        m_hat, v_hat = self.m / (1 - 0.9**self.t), self.v / (1 - 0.999**self.t)
        result: np.ndarray = vector - self.rate * m_hat / (np.sqrt(v_hat) + 1e-8)
        return result


def initial_net(train_rows: np.ndarray, seed: int, hidden: int = MLP_HIDDEN) -> TanhNet:
    """Gain fit on the training rows; small random input weights; readout 0."""
    width = train_rows.shape[1]
    rng = np.random.default_rng(seed)
    return TanhNet(
        gain=fit_input_gain(train_rows),
        w_in=rng.standard_normal((hidden, width)) / np.sqrt(width),
        b_in=np.zeros(hidden),
        w_out=np.zeros(hidden),
        w_skip=np.zeros(width),
        bias=0.0,
    )


def fit_mlp(
    train: tuple[np.ndarray, np.ndarray], valid: tuple[np.ndarray, np.ndarray], seed: int
) -> TanhNet:
    """Minibatch Adam on the class-weighted loss, stopped early on the validation repositories.

    Raises ValueError (from `class_weights`) when either split has only one class.
    """
    net = initial_net(train[0], seed)
    x, y = net.gain.apply(train[0]), train[1].astype(bool)
    vx, vy = net.gain.apply(valid[0]), valid[1].astype(bool)
    weights, vweights = class_weights(y), class_weights(vy)
    adam, rng = _Adam(len(net.as_vector()), ADAM_RATE), np.random.default_rng([seed, 1])
    best, best_loss, stale = net, np.inf, 0
    for _ in range(EPOCHS):
        net = _epoch(net, adam, (x, y, weights), rng)
        loss = weighted_loss(net, vx, vy, vweights)
        best, best_loss, stale = (
            (net, loss, 0) if loss < best_loss else (best, best_loss, stale + 1)
        )
        if stale >= PATIENCE:
            break
    return best


def _epoch(
    net: TanhNet,
    adam: _Adam,
    data: tuple[np.ndarray, np.ndarray, np.ndarray],
    rng: np.random.Generator,
) -> TanhNet:
    x, y, weights = data
    vector, order = net.as_vector(), rng.permutation(len(x))
    for start in range(0, len(x), BATCH):
        pick = order[start : start + BATCH]
        grad = gradient(net.with_vector(vector), x[pick], y[pick], weights[pick]) / len(pick)
        vector = adam.step(vector, grad)
    return net.with_vector(vector)


def fine_tune(
    net: TanhNet, rows: np.ndarray, labels: np.ndarray, weights: np.ndarray, anchor: float
) -> TanhNet:
    """Full-batch Adam from `net`, pulled back toward it with strength `anchor` (L2)."""
    x, y = net.gain.apply(rows), labels.astype(bool)
    start = net.as_vector()
    vector, adam = start.copy(), _Adam(len(start), FINE_TUNE_RATE)
    for _ in range(FINE_TUNE_STEPS):
        grad = gradient(net.with_vector(vector), x, y, weights) + anchor * (vector - start)
        vector = adam.step(vector, grad)
    return net.with_vector(vector)
