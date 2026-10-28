"""Mushroom body: a learner with the fly's mushroom-body circuit counts.

Violation prevented: **Paper Tiger**. A network that only matches the shape
of the fly's circuit, without learning anything the counters cannot, passes
its tests and helps nobody. It must stand next to Counters and Similarity on
the same offline comparison and be judged by it; no claim is made here about
how quickly it learns.

The circuit: 86 inputs feed 5,177 Kenyon cells (KCs), each listening to 7
inputs. Only the top 5% (259 cells) fire. One output weight per cell is
changed by a local, dopamine-like rule when trouble followed (the weights of
the active cells are cut) and relaxed back when it did not. No gradients, no
backprop. Learning is overlap-limited: a pattern that shares few active cells
with a punished one barely moves.

State is passed in and returned, never held, so a run can be replayed and a
learner swapped without hidden mutable state (**Shield**): `learn` returns a
new `MushroomState` and leaves the old arrays untouched. Wiring uses the fly's
published counts (86 inputs, 5,177 cells, 7 inputs per cell, 5% firing) with
random connections by default, from the seed. Real FlyWire wiring, a learner
built on the fly's actual circuit, is an optional user download, never
committed and never fetched by code; asking for it and not supplying a valid
file raises, because quietly substituting random wiring would make a result
look like the real circuit when it is not (**Silent Fallback**). If you use
FlyWire data, cite it as FlyWire asks.

Recall considers only earlier steps that share a word (command or file name)
with the current one, and candidates are kept with their cell codes so a
decision costs its matches, not the size of history (**Computational
Friction**); the tests keep the plain scan as an oracle.

`trouble_threshold` is a constructor parameter, not a tuned constant. The
default is an explicit placeholder; the pre-registration fixes the real value
after calibration on the train split.

FlyWire file format: an `.npz` holding `kc_inputs`, an int array of shape
(5177, k) whose entries index the 86 inputs.
"""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np

from symbiont.core.features import (
    N_FEATURES,
    ScratchFile,
    featurise,
    meaningful_history,
)
from symbiont.core.indexes import Growing, PainPointIndex, TokenIndex, continues, tokens
from symbiont.core.meta import (
    CALIBRATOR_RATE,
    META_RUN_SEED,
    Calibrator,
    LinearReadoutMeta,
    Readout,
    calibrator_step,
)
from symbiont.core.similarity import RECALL_SIZE
from symbiont.core.slot import NO_HISTORY, Decision, Outcome, Situation
from symbiont.miner.painpoint import PainPoint, Signature
from symbiont.records.schema import Record

N_KC = 5177
N_ACTIVE = 259  # top 5% of the cells
INPUTS_PER_KC = 7
PLACEHOLDER_THRESHOLD = 0.9  # not tuned; the prereg sets the real value
_RELAX = 0.1  # relaxing is a tenth as strong as depressing
# One punishment leaves the score at exactly 1 - lr, which is the placeholder
# threshold; float rounding must not decide that boundary. A score within this
# tolerance of the threshold counts as not below it.
SCORE_TOLERANCE = 1e-9
_JITTER_SCALE = 1e-6  # input features move in steps far larger than this


@dataclass(frozen=True)
class MushroomState:
    """Wiring and output weights of one run; `learn` returns a new one."""

    inputs: np.ndarray  # (N_KC, k) int: the sparse input-to-cell wiring, every weight 1
    w_out: np.ndarray  # (N_KC,) float: output weight per cell, starts at 1.0
    lr: float
    jitter: np.ndarray  # (N_KC,) fixed per-cell tie-break, far below any real input difference
    # Each kind of trouble this state was punished for, with every cell that
    # was active when it happened (a bool mask, never mutated after creation).
    learned: tuple[tuple[Signature, np.ndarray], ...] = ()
    updates: int = 0
    # Meta-learnable together with `w_out`; see symbiont.core.meta.
    calibrator: Calibrator = Calibrator()


@dataclass(eq=False, repr=False)
class Mushroom(LinearReadoutMeta):
    """The fly's mushroom-body learner.

    A dataclass so the constructor settings are plain fields (seed, wiring,
    and the filters the pre-registration fixes), while the memos below are
    private and never read for anything but speed.
    """

    seed: int
    wiring: Literal["random", "flywire"] = "random"
    flywire_path: Path | None = None
    lr: float = 0.1
    trouble_threshold: float = PLACEHOLDER_THRESHOLD
    calibrator_rate: float = CALIBRATOR_RATE  # fixed per run, never self-tuned
    hubs: frozenset[str] = frozenset()
    scratch: frozenset[ScratchFile] = frozenset()
    name = "mushroom"

    def __post_init__(self) -> None:
        """Set up the private memos; they are never read for anything but speed."""
        self._hubs = self.hubs
        self._scratch = self.scratch
        # For the dashboard only: which cells fired on the last decide. No
        # decision ever reads it.
        self.last_activity: np.ndarray | None = None
        # A memo of each candidate's cell code, never read for anything but
        # speed: a candidate's code is fixed once it is in history.
        self._recall_index = _RecallIndex()
        self._history_index = PainPointIndex()
        self._packed_for: tuple[tuple[Signature, np.ndarray], ...] | None = None
        self._packed = np.zeros((0, 0), np.uint8)
        self._meta_base: MushroomState | None = None

    def base_state(self) -> MushroomState:
        """Fixed wiring of the meta-learnable fly: never meta-learned (spec 4.5)."""
        if self._meta_base is None:
            self._meta_base = self.initial_state(META_RUN_SEED)
        return self._meta_base

    def readout_view(self, x: np.ndarray, state: MushroomState) -> Readout:
        """The score is `1 - mean(w_out[active])`, which is linear in `w_out`."""
        return Readout(phi=-kc_code(x, state).astype(np.float64) / N_ACTIVE, offset=1.0)

    def initial_state(self, seed: int) -> MushroomState:
        """Fresh weights (all 1) with wiring from the learner's seed and `seed`."""
        if self.wiring == "flywire":
            inputs = _load_flywire(self.flywire_path)
        else:
            inputs = _random_wiring(np.random.default_rng([self.seed, seed]))
        jitter = np.random.default_rng([self.seed, seed, 1]).random(N_KC) * _JITTER_SCALE
        return MushroomState(inputs=inputs, w_out=np.ones(N_KC), lr=self.lr, jitter=jitter)

    def decide(self, x: np.ndarray, situation: Situation, state: MushroomState) -> Decision:
        """Warn when this step's cells were pushed down; always report the risk."""
        if not situation.history and not situation.candidates and not state.updates:
            return _quiet(NO_HISTORY)
        if not situation.session_prefix:
            return _quiet("the session has not started")
        code = kc_code(x, state)
        self.last_activity = code
        score = float(state.w_out[code].sum()) / N_ACTIVE
        recalled = self._recall(code, situation, state)
        risk = 1.0 - score
        low = score < self.trouble_threshold - SCORE_TOLERANCE
        trouble, why = self._kind_of_trouble(code, situation, state) if low else (None, ())
        if trouble is None and not recalled:
            return _quiet(
                "this step looks like past trouble, but of no kind that was recorded"
                if low
                else "this step looks like nothing that went wrong before",
                risk=risk,
            )
        return Decision(trouble=trouble, why=why, recall=recalled, reason_none=None, risk=risk)

    def learn(self, x: np.ndarray, outcome: Outcome, state: MushroomState) -> MushroomState:
        """Cut the active cells when trouble followed; relax them when it did not.

        A false alarm relaxes `false_alarm_cost` times as hard (capped at a
        full return to 1.0); the balanced cost of 1 is the original rule.
        """
        code = kc_code(x, state)
        raw = 1.0 - float(state.w_out[code].sum()) / N_ACTIVE
        weights = state.w_out.copy()
        if outcome.pain_point_followed:
            weights[code] *= 1 - state.lr
        else:
            relax = min(1.0, _RELAX * outcome.false_alarm_cost)
            weights[code] += state.lr * (1 - weights[code]) * relax
        learned = state.learned
        if outcome.pain_point_followed and outcome.signature is not None:
            learned = _remember(learned, outcome.signature, code)
        return replace(
            state,
            w_out=weights,
            learned=learned,
            updates=state.updates + 1,
            calibrator=calibrator_step(state.calibrator, raw, outcome, self.calibrator_rate),
        )

    def _kind_of_trouble(
        self, code: np.ndarray, situation: Situation, state: MushroomState
    ) -> tuple[Signature | None, tuple[PainPoint, ...]]:
        """The recorded kind of trouble whose cells this step shares most.

        Ties fall to the signature's text. Its evidence is the project's mined
        history of that same kind (possibly none, if it was only learned).
        """
        best = self._most_shared_kind(code, state)
        if best is None:
            return None, ()
        self._history_index.sync(situation.history)
        of_that_kind = replace(situation, history=tuple(self._history_index.with_signature(best)))
        return best, tuple(meaningful_history(of_that_kind, self._hubs, self._scratch))

    def _most_shared_kind(self, code: np.ndarray, state: MushroomState) -> Signature | None:
        """The learned kind of trouble sharing most cells with `code`, or None.

        Ties go to the signature's text. The masks are packed into bits once
        per learned tuple (a state's `learned` does not change while a session
        is decided).
        """
        if self._packed_for is not state.learned:
            self._packed = (
                np.packbits(np.stack([m for _, m in state.learned]), axis=1)
                if state.learned
                else np.zeros((0, 0), np.uint8)
            )
            self._packed_for = state.learned
        if not len(self._packed):
            return None
        counts = np.bitwise_count(self._packed & np.packbits(code)).sum(axis=1, dtype=np.int64)
        most = counts.max()
        if most == 0:
            return None
        return min(
            (state.learned[i][0] for i in np.flatnonzero(counts == most)),
            key=lambda sig: (sig.signal.value, sig.key),
        )

    def _recall(
        self, code: np.ndarray, situation: Situation, state: MushroomState
    ) -> tuple[Record, ...]:
        """Earlier steps that share cells with this one, weighted by push-down.

        Only steps sharing a word (command or file name) with this one are
        considered, as in Similarity.
        """
        current = situation.session_prefix[-1]
        index = self._recall_index
        index.sync(situation, state, self._hubs, self._scratch)
        eligible = index.tokens.sharing_a_word(set(tokens(current)))
        eligible[index.tokens.not_before(current)] = False
        return tuple(index.tokens.record(i) for i in index.best(code, eligible, state.w_out))


class _RecallIndex:
    """Candidates held with their cell codes.

    Many candidates share one code
    (a code depends only on the step's own command, files and outcome), so
    candidates are grouped by code and each cell lists the groups that fire
    it. A candidate's score is the sum, over the cells it shares with the
    current code, of how far each was pushed down (1 - weight); only cells
    that were pushed down need visiting, and the winners are re-scored with the
    exact formula so ties and rounding fall as a full scan would.
    """

    def __init__(self) -> None:
        self.tokens = TokenIndex()
        self._reset(None)

    def _reset(self, wiring: tuple[np.ndarray, np.ndarray] | None) -> None:
        self._wiring = wiring
        self._group_of = Growing(np.int32)  # candidate position -> code group
        self._groups: dict[bytes, int] = {}
        self._codes: list[np.ndarray] = []  # per group: its cells, ascending
        self._cells = [Growing(np.int32) for _ in range(N_KC)]  # per cell: groups firing it

    def sync(
        self,
        situation: Situation,
        state: MushroomState,
        hubs: frozenset[str],
        scratch: frozenset[ScratchFile],
    ) -> None:
        wiring = (state.inputs, state.jitter)
        same = self._wiring is not None and all(
            a is b for a, b in zip(wiring, self._wiring, strict=True)
        )
        if not same or not continues(self.tokens._items, situation.candidates):
            self.tokens = TokenIndex()
            self._reset(wiring)
        self.tokens.sync(situation.candidates)
        for pos in range(self._group_of.size, len(situation.candidates)):
            context = Situation(situation.project, (situation.candidates[pos],), (), ())
            cells = np.flatnonzero(kc_code(featurise(context, hubs=hubs, scratch=scratch), state))
            self._group_of.append(self._group(cells.astype(np.int16)))

    def _group(self, cells: np.ndarray) -> int:
        key = cells.tobytes()
        if key not in self._groups:
            self._groups[key] = len(self._codes)
            self._codes.append(cells)
            for cell in cells:
                self._cells[cell].append(self._groups[key])
        return self._groups[key]

    def best(self, code: np.ndarray, eligible: np.ndarray, w_out: np.ndarray) -> list[int]:
        pushed = 1.0 - w_out
        by_group = np.zeros(len(self._codes))
        for cell in np.flatnonzero(code & (pushed > 0)):
            by_group[self._cells[cell].view] += pushed[cell]
        group_of = self._group_of.view
        scores = by_group[group_of]
        scores[~eligible] = 0.0
        exact_by_group: dict[int, float] = {}
        exact = []
        for i in best_first_with_ties(scores, RECALL_SIZE):
            group = int(group_of[i])
            if group not in exact_by_group:
                exact_by_group[group] = _exact_score(code, self._codes[group], w_out)
            exact.append((exact_by_group[group], i))
        ranked = sorted(((s, i) for s, i in exact if s > 0), key=lambda si: (-si[0], si[1]))
        return [i for _, i in ranked[:RECALL_SIZE]]


_TIE_ROOM = 1e-9  # the fast sum and the exact formula differ by rounding only


def best_first_with_ties(scores: np.ndarray, size: int) -> list[int]:
    """Positions whose score is within rounding of the k-th best or better."""
    positive = np.flatnonzero(scores > 0)
    if len(positive) <= size:
        return [int(i) for i in positive]
    cutoff = np.partition(scores[positive], -size)[-size]
    return [int(i) for i in positive[scores[positive] >= cutoff - _TIE_ROOM]]


def _exact_score(code: np.ndarray, theirs: np.ndarray, w_out: np.ndarray) -> float:
    cells = theirs[code[theirs]]  # ascending, as a boolean mask would give
    if len(cells) == 0:
        return 0.0
    return float(len(cells)) * (1.0 - float(w_out[cells].mean()))


def kc_code(x: np.ndarray, state: MushroomState) -> np.ndarray:
    """Which cells fire for input `x`: exactly the N_ACTIVE with the largest drive.

    Real inputs are sparse one-hots, so many cells tie; a fixed seeded
    per-cell jitter breaks those ties, so the same input always gives the same
    code without the lowest-numbered cells always winning.
    """
    drive = x[state.inputs].sum(axis=1, dtype=np.float64) + state.jitter
    # The N_ACTIVE largest, ties to the lower cell: what a stable argsort of
    # -drive would pick, without sorting all 5,177 cells.
    cutoff = np.partition(drive, -N_ACTIVE)[-N_ACTIVE]
    code: np.ndarray = drive > cutoff
    code[np.flatnonzero(drive == cutoff)[: N_ACTIVE - int(code.sum())]] = True
    return code


def _remember(
    learned: tuple[tuple[Signature, np.ndarray], ...],
    signature: Signature,
    code: np.ndarray,
) -> tuple[tuple[Signature, np.ndarray], ...]:
    """Add this code to the signature's cells, as new tuples and arrays."""
    kept = tuple((sig, mask) for sig, mask in learned if sig != signature)
    old = next((mask for sig, mask in learned if sig == signature), np.zeros(N_KC, dtype=bool))
    return kept + ((signature, old | code),)


def _quiet(reason: str, *, risk: float = 0.0) -> Decision:
    return Decision(trouble=None, why=(), recall=(), reason_none=reason, risk=risk)


def _random_wiring(rng: np.random.Generator) -> np.ndarray:
    return np.stack(
        [rng.choice(N_FEATURES, size=INPUTS_PER_KC, replace=False) for _ in range(N_KC)]
    )


def _load_flywire(path: Path | None) -> np.ndarray:
    if path is None:
        raise ValueError("FlyWire wiring was asked for but no flywire_path was given")
    if not Path(path).is_file():
        raise FileNotFoundError(
            f"FlyWire wiring file not found: {path} (it is an optional user download)"
        )
    try:
        with np.load(path) as archive:
            inputs: np.ndarray = archive["kc_inputs"]
    except (OSError, ValueError, KeyError) as err:
        raise ValueError(
            f"FlyWire wiring file {path} is not a readable .npz with 'kc_inputs'"
        ) from err
    if inputs.ndim != 2 or inputs.shape[0] != N_KC or not np.issubdtype(inputs.dtype, np.integer):
        raise ValueError(
            f"kc_inputs must be an integer array of shape ({N_KC}, k), got {inputs.shape}"
        )
    if inputs.min() < 0 or inputs.max() >= N_FEATURES:
        raise ValueError(f"kc_inputs entries must index the {N_FEATURES} inputs")
    return inputs
