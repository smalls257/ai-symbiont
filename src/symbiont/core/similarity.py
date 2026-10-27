"""Similarity: recall of past steps that look like this one. A reference row.

Violation prevented: **Paper Tiger**. Remembering the nearest past work, with
no judgement at all, is the cheapest thing that could help; the fly network
must do better. It flags nothing. Recall returns the stored `Record` objects
themselves, never text copies, so a note can quote what really happened
(**Anchor**). Scoring is a pure function of the texts (**Infected Core**).

Cost: the candidates are held in an inverted index (`TokenIndex`) that grows
with history, and only the documents sharing a query word are scored
(**Computational Friction**); the ranking is the same as scoring them all.
"""

import numpy as np

from symbiont.core.indexes import Bm25Shape, TokenIndex, tokens
from symbiont.core.slot import NO_HISTORY, Decision, Outcome, Situation

RECALL_SIZE = 3
_BM25 = Bm25Shape(term_saturation=1.5, length_normalisation=0.75)


class Similarity:
    """Decider that never warns and recalls the three closest past steps."""

    name = "similarity"

    def __init__(self) -> None:
        # A memo of the candidates seen so far, never read for anything but speed.
        self._index = TokenIndex()

    def initial_state(self, seed: int) -> None:
        """Stateless: the index is a memo, not learned state."""
        return

    def decide(self, x: np.ndarray, situation: Situation, state: None) -> Decision:
        """Recall the closest past steps, or stay quiet with the reason."""
        if not situation.history and not situation.candidates:
            return _quiet(NO_HISTORY)
        if not situation.session_prefix:
            return _quiet("the session has not started")
        current = situation.session_prefix[-1]
        self._index.sync(situation.candidates)
        best = self._index.bm25_top(
            set(tokens(current)), self._index.not_before(current), RECALL_SIZE, _BM25
        )
        if not best:
            return _quiet("nothing in past work resembles this step")
        return Decision(
            trouble=None,
            why=(),
            recall=tuple(self._index.record(p) for p in best),
            reason_none=None,
        )

    def learn(self, x: np.ndarray, outcome: Outcome, state: None) -> None:
        """Nothing to learn; recall is a pure function of the texts."""
        return


def _quiet(reason: str) -> Decision:
    return Decision(trouble=None, why=(), recall=(), reason_none=reason)
