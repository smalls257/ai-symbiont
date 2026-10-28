"""DenseNet: a plain small network built from scratch, the second filler.

Same 86 features and contract as the fly (readout, calibrator, local rule, `MetaLearnable`), so it
is a fair second row. One hidden layer of `N_HIDDEN` tanh units with fixed seeded weights and a
linear readout; only the readout and calibrator learn, by the delta rule. State is passed in and
returned. Recall considers earlier steps sharing a word, scored by hidden-activity overlap.
"""

from dataclasses import dataclass, replace

import numpy as np

from symbiont.core.features import N_FEATURES, ScratchFile, featurise, meaningful_history
from symbiont.core.indexes import PainPointIndex, TokenIndex, continues, tokens
from symbiont.core.meta import (
    CALIBRATOR_RATE,
    META_RUN_SEED,
    Calibrator,
    LinearReadoutMeta,
    Readout,
    calibrator_step,
    weighted_dz,
)
from symbiont.core.similarity import RECALL_SIZE
from symbiont.core.slot import NO_HISTORY, Decision, Outcome, Situation
from symbiont.miner.painpoint import PainPoint, Signature
from symbiont.records.schema import Record

# 128 units separate the 86 features linearly and keep the readout small enough to move within
# ~10 outcomes of a new domain; far below the fly's 5,177 cells on purpose (size vs. sparsity).
N_HIDDEN = 128
# Delta-rule step: under one logit per outcome, stable at false-alarm costs up to 4
# (2 and 4 diverged with the scale-coupled step). Fixed, not tuned.
READOUT_RATE = 1.0
# Flag above 0.5 calibrated probability: the cost-aware Bayes threshold; a prereg may move it.
PLACEHOLDER_THRESHOLD = 0.5


@dataclass(frozen=True)
class DenseState:
    """Hidden weights (fixed) and readout of one run; `learn` returns a new one."""

    hidden_w: np.ndarray  # (N_HIDDEN, N_FEATURES), fixed from the seed
    w_out: np.ndarray  # (N_HIDDEN,) readout, starts at 0
    lr: float
    # Each kind of trouble this state saw, with the summed hidden activity of
    # the steps it followed (never mutated after creation).
    learned: tuple[tuple[Signature, np.ndarray], ...] = ()
    updates: int = 0
    calibrator: Calibrator = Calibrator()


def activity(x: np.ndarray, state: DenseState) -> np.ndarray:
    """Hidden activity of input `x`, scaled so its squared norm is at most 1."""
    hidden: np.ndarray = np.tanh(state.hidden_w @ x) / np.sqrt(N_HIDDEN)
    return hidden


@dataclass(eq=False, repr=False)
class DenseNet(LinearReadoutMeta):
    """A from-scratch small network filling the same slot as the fly."""

    seed: int
    lr: float = READOUT_RATE
    trouble_threshold: float = PLACEHOLDER_THRESHOLD
    calibrator_rate: float = CALIBRATOR_RATE  # fixed per run, never self-tuned
    hubs: frozenset[str] = frozenset()
    scratch: frozenset[ScratchFile] = frozenset()
    name = "dense"

    def __post_init__(self) -> None:
        """Set up the private memos; they are never read for anything but speed."""
        self._hubs = self.hubs
        self._scratch = self.scratch
        # Memos, never read for anything but speed.
        self._candidates = _CandidateActivity()
        self._history_index = PainPointIndex()
        self._meta_base: DenseState | None = None

    def initial_state(self, seed: int) -> DenseState:
        """Random fixed hidden layer from the learner's seed and `seed`; readout 0."""
        rng = np.random.default_rng([self.seed, seed])
        hidden = rng.standard_normal((N_HIDDEN, N_FEATURES))
        return DenseState(hidden_w=hidden, w_out=np.zeros(N_HIDDEN), lr=self.lr)

    def base_state(self) -> DenseState:
        """Fixed hidden layer of the meta-learnable net: never meta-learned."""
        if self._meta_base is None:
            self._meta_base = self.initial_state(META_RUN_SEED)
        return self._meta_base

    def readout_view(self, x: np.ndarray, state: DenseState) -> Readout:
        """The score is the readout dotted with hidden activity."""
        return Readout(phi=activity(x, state))

    def decide(self, x: np.ndarray, situation: Situation, state: DenseState) -> Decision:
        """Warn when the calibrated probability of trouble passes the threshold."""
        if not situation.history and not situation.candidates and not state.updates:
            return _quiet(NO_HISTORY)
        if not situation.session_prefix:
            return _quiet("the session has not started")
        probability = self.trouble_probability(x, state)
        recalled = self._recall(activity(x, state), situation, state)
        high = probability > self.trouble_threshold
        trouble, why = self._kind_of_trouble(x, situation, state) if high else (None, ())
        if trouble is None and not recalled:
            return _quiet(
                "this step looks like past trouble, but of no kind that was recorded"
                if high
                else "this step looks like nothing that went wrong before",
                risk=probability,
            )
        return Decision(trouble, why, recalled, None, risk=probability)

    def learn(self, x: np.ndarray, outcome: Outcome, state: DenseState) -> DenseState:
        """Delta rule on the readout (no calibrator scale), online step on the calibrator."""
        view = self.readout_view(x, state)
        raw = view.raw(state.w_out)
        error = weighted_dz(state.calibrator.probability(raw), outcome)
        learned = state.learned
        if outcome.pain_point_followed and outcome.signature is not None:
            learned = _remember(learned, outcome.signature, view.phi)
        return replace(
            state,
            w_out=state.w_out - state.lr * error * view.phi,
            calibrator=calibrator_step(state.calibrator, raw, outcome, self.calibrator_rate),
            learned=learned,
            updates=state.updates + 1,
        )

    def _kind_of_trouble(
        self, x: np.ndarray, situation: Situation, state: DenseState
    ) -> tuple[Signature | None, tuple[PainPoint, ...]]:
        """The recorded kind of trouble whose past activity this step overlaps most."""
        best = _most_overlapping_kind(activity(x, state), state)
        if best is None:
            return None, ()
        self._history_index.sync(situation.history)
        of_that_kind = replace(situation, history=tuple(self._history_index.with_signature(best)))
        return best, tuple(meaningful_history(of_that_kind, self._hubs, self._scratch))

    def _recall(
        self, phi: np.ndarray, situation: Situation, state: DenseState
    ) -> tuple[Record, ...]:
        """Earlier steps whose activity overlaps this one on units pushed toward trouble."""
        current = situation.session_prefix[-1]
        memo = self._candidates
        memo.sync(situation, state, self._hubs, self._scratch)
        eligible = memo.tokens.sharing_a_word(set(tokens(current)))
        eligible[memo.tokens.not_before(current)] = False
        scores = memo.activities() @ (np.maximum(state.w_out, 0.0) * phi)
        scores[~eligible] = 0.0
        ranked = sorted(np.flatnonzero(scores > 0), key=lambda pos: (-scores[pos], pos))
        return tuple(memo.tokens.record(int(i)) for i in ranked[:RECALL_SIZE])


class _CandidateActivity:
    """Candidates held with their hidden activity, computed once each."""

    def __init__(self) -> None:
        """Start empty; rows fill in as `sync` sees candidates."""
        self.tokens = TokenIndex()
        self._hidden_w: np.ndarray | None = None
        self._rows: list[np.ndarray] = []

    def sync(
        self,
        situation: Situation,
        state: DenseState,
        hubs: frozenset[str],
        scratch: frozenset[ScratchFile],
    ) -> None:
        """Extend the per-candidate hidden activity; rebuild when the weights or history change."""
        stale = self._hidden_w is not state.hidden_w
        if stale or not continues(self.tokens._items, situation.candidates):
            self.tokens = TokenIndex()
            self._rows = []
            self._hidden_w = state.hidden_w
        self.tokens.sync(situation.candidates)
        for record in situation.candidates[len(self._rows) :]:
            context = Situation(situation.project, (record,), (), ())
            self._rows.append(activity(featurise(context, hubs=hubs, scratch=scratch), state))

    def activities(self) -> np.ndarray:
        """One row of hidden activity per candidate, in candidate order."""
        if not self._rows:
            return np.zeros((0, N_HIDDEN))
        return np.stack(self._rows)


def _most_overlapping_kind(phi: np.ndarray, state: DenseState) -> Signature | None:
    """The learned kind whose summed activity overlaps `phi` most; ties go to its text."""
    if not state.learned:
        return None
    overlaps = [(float(vector @ phi), sig) for sig, vector in state.learned]
    best = max(overlap for overlap, _ in overlaps)
    if best <= 0:
        return None
    return min(
        (sig for overlap, sig in overlaps if overlap == best),
        key=lambda sig: (sig.signal.value, sig.key),
    )


def _remember(
    learned: tuple[tuple[Signature, np.ndarray], ...], signature: Signature, phi: np.ndarray
) -> tuple[tuple[Signature, np.ndarray], ...]:
    """Add this activity to the signature's sum, as new tuples and arrays."""
    kept = tuple((sig, vec) for sig, vec in learned if sig != signature)
    old = next((vec for sig, vec in learned if sig == signature), np.zeros(N_HIDDEN))
    return kept + ((signature, old + phi),)


def _quiet(reason: str, *, risk: float = 0.0) -> Decision:
    """A decision that says nothing, with the reason and the risk."""
    return Decision(trouble=None, why=(), recall=(), reason_none=reason, risk=risk)
