"""Counters: the plainest learner, and a reference row for the fly network.

Violation prevented: **Paper Tiger**. A learner that cannot beat "has this
file or command gone wrong twice before?" has not earned its place, so this
is the bar. State is an immutable tally passed in and returned, never held
(**Infected Core**), and a quiet answer always says why (**Silent Fallback**).

Features: the counters' view of the 86 numbers is `COUNTER_FEATURES`
(position, file history, lines added, edit kind). The flag rule itself needs
none of them; it works on pain-point history, so `x` is accepted for the
slot's sake and not read.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import replace

import numpy as np

from symbiont.core.features import ScratchFile, meaningful_history
from symbiont.core.indexes import PainPointIndex
from symbiont.core.slot import NO_HISTORY, Decision, Outcome, Situation
from symbiont.miner.commands import normalise_command
from symbiont.miner.painpoint import PainPoint, Signature
from symbiont.records.schema import Record

Event = tuple[str, int, Signature]  # (session_id, step, what went wrong)
Tally = frozenset[Event]


class Counters:
    """Flags a file or command once it has gone wrong `min_count` times before."""

    name = "counters"

    def __init__(
        self,
        min_count: int = 2,
        *,
        hubs: frozenset[str] = frozenset(),
        scratch: frozenset[ScratchFile] = frozenset(),
    ) -> None:
        self.min_count = min_count
        self._hubs = hubs
        self._scratch = scratch
        # Memos of history and of the learned tally, never read for anything
        # but speed: a decision looks only at what matches the current step.
        self._history_index = PainPointIndex()
        self._learned_index = PainPointIndex()
        self._learned_from: Tally | None = None

    def initial_state(self, seed: int) -> Tally:
        """No learned events yet."""
        return frozenset()

    def decide(self, x: np.ndarray, situation: Situation, state: Tally | None) -> Decision:
        """Warn when this step's file or command has enough matching past trouble."""
        learned = state or frozenset()
        if not situation.history and not learned:
            return _quiet(NO_HISTORY)
        current = situation.session_prefix[-1] if situation.session_prefix else None
        if current is None:
            return _quiet("the session has not started")
        candidates = self._matching(situation, learned, current, _normalised(current))
        known = replace(situation, history=tuple(candidates))
        past = _each_event_once(meaningful_history(known, self._hubs, self._scratch))
        return self._verdict(past)

    def _verdict(self, past: list[PainPoint]) -> Decision:
        """Name the commonest kind of trouble among `past` if it is common enough."""
        risk = float(len(past))
        if not past:
            return _quiet("nothing has gone wrong on this file or command before", risk=risk)
        seen = Counter(p.signature for p in past)
        # Highest count first; ties fall to the signature's own text so the
        # answer never depends on hash order or input order.
        worst = min(seen, key=lambda sig: (-seen[sig], sig.signal.value, sig.key))
        if seen[worst] < self.min_count:
            return _quiet(
                "this file or command has not gone wrong often enough to worry about", risk=risk
            )
        return Decision(
            trouble=worst,
            why=tuple(p for p in past if p.signature == worst),
            recall=(),
            reason_none=None,
            risk=risk,
        )

    def _matching(
        self, situation: Situation, learned: Tally, current: Record, command: tuple[str, ...] | None
    ) -> list[PainPoint]:
        """History and learned points that concern this step, history first.

        Learned events are ordered by their own fields so the answer never
        depends on set iteration order.
        """
        self._history_index.sync(situation.history)
        if learned is not self._learned_from:
            ordered = sorted(learned, key=lambda ev: (ev[0], ev[1], ev[2].signal.value, ev[2].key))
            self._learned_index = PainPointIndex()
            self._learned_index.sync([_as_pain_point(e) for e in ordered])
            self._learned_from = learned
        return [
            *self._history_index.matching(current.files, command),
            *self._learned_index.matching(current.files, command),
        ]

    def learn(self, x: np.ndarray, outcome: Outcome, state: Tally | None) -> Tally:
        """Remember trouble that followed; a calm outcome changes nothing."""
        learned = state or frozenset()
        if not outcome.pain_point_followed or outcome.signature is None:
            return learned
        if outcome.session_id is None or outcome.step is None:
            # Unplaced trouble cannot match anything in history, so it is its own event.
            return learned | {("", -(len(learned) + 1), outcome.signature)}
        return learned | {(outcome.session_id, outcome.step, outcome.signature)}


def _as_pain_point(event: Event) -> PainPoint:
    session_id, step, signature = event
    return PainPoint(signature, session_id, step, ())


def _each_event_once(points: Iterable[PainPoint]) -> list[PainPoint]:
    """One pain point per (session, step, signature); the first seen wins.

    A mined point (which knows its records) beats a learned one.
    """
    unique: dict[Event, PainPoint] = {}
    for p in points:
        unique.setdefault((p.session_id, p.step, p.signature), p)
    return list(unique.values())


def _quiet(reason: str, *, risk: float = 0.0) -> Decision:
    return Decision(trouble=None, why=(), recall=(), reason_none=reason, risk=risk)


def _normalised(current: Record) -> tuple[str, ...] | None:
    return tuple(normalise_command(current.command)) if current.command else None
