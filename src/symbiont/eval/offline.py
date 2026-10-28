"""Offline replay: replay recorded sessions through a Decider and score it.

Violation prevented: **Paper Tiger**. A fly-circuit learner that passes its
unit tests but warns no better than "has this gone wrong twice before?" would
ship as a feature nobody benefits from. So the replay scores every learner on
the same steps, the table cannot be rendered without the counters and
similarity rows beside the fly row, and the live-learner choice is a rule
(`fly_default`) fixed in the pre-registration, not a judgment made after
seeing the numbers.

Second guard, **Infected Core**: nothing here reads a file, a clock or a
network. Sessions, references and history come in as arguments; the run
script (periphery) loads the data. Tests use synthetic sessions.

What a step is scored on (the pre-registration states the same):

- flag: did the decider name a trouble (`Decision.trouble is not None`)?
- label: does a pain point (after hub and scratch-file filtering, see
  `pain_labels`) fall in steps t+1..t+5 of the same session?
- balanced accuracy (AUROC of the binary flag): flags are binary, so AUROC
  with ties counted as half equals (true-positive rate + true-negative rate)
  / 2. It is 0.5 for a decider that never flags.
- recall@3 (only the first RECALL_SIZE recalled records are looked at): at
  steps with a next pain point, does any recalled record belong to a history
  pain point of the same signature as that next pain point? Only reported for
  a decider that recalled something at some step.

Same filter everywhere: history is stored already filtered by `pain_labels`
(hub breakage and rework of a session's own scratch files removed), the same
function that makes the labels, so learners and labels agree by construction.

Replay can resume: it takes a trained state and returns the final one, so a
learner can replay the train sessions online and then continue through the
test sessions with what it learned, while only the new sessions are scored.

Leak rule: a decision at step t sees pain points mined from earlier,
finished sessions only. Pain points of the current session are placed after
the fact (a blast-radius point sits at the edit but is found when the test
fails), so reading them mid-session would hand the answer over. Learning
happens after each session ends.

The verdict rule lives in `offline_verdict`, the markdown table in
`offline_table`; both read the scores defined here.
"""

import logging
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import numpy as np

from symbiont.core.features import featurise, meaningful_history, scratch_files
from symbiont.core.similarity import RECALL_SIZE
from symbiont.core.slot import Decider, Decision, Outcome, Situation
from symbiont.miner.mine import References, mine_session
from symbiont.miner.painpoint import PainPoint, RecordRef, Signature
from symbiont.records.schema import Record

log = logging.getLogger(__name__)

WINDOW = 5


def pain_labels(
    session: Sequence[Record], references: References, hubs: frozenset[str]
) -> list[PainPoint]:
    """The pain points that count as mistakes.

    Breakage of a hub module and rework of a file the session made for itself
    are dropped. Labels and the history learners read both come from here.
    """
    mined = tuple(mine_session(session, references))
    empty = Situation(project="", session_prefix=(), history=mined, candidates=())
    return meaningful_history(empty, hubs, scratch_files(session))


@dataclass
class ReplayContext:
    """What does not depend on the learner, computed once and shared by replays.

    Filtered pain points per session, and the 86 features per step. A features
    entry is only valid for the history it was made with, so the key includes
    its size; replays must therefore walk the same sessions in the same order.
    """

    references: References
    hubs: frozenset[str]
    _labels: dict[str, tuple[Record, list[PainPoint]]] = field(default_factory=dict, repr=False)
    _features: dict[tuple[str, int, int], np.ndarray] = field(default_factory=dict, repr=False)

    def labels(self, session: Sequence[Record]) -> list[PainPoint]:
        """Filtered pain points of one session; raises if two sessions share an id."""
        sid = session[0].session_id
        if sid not in self._labels:
            self._labels[sid] = (session[0], pain_labels(session, self.references, self.hubs))
        first, points = self._labels[sid]
        if first != session[0]:
            raise ValueError(f"two different sessions share the same id {sid}")
        return points

    def features(self, situation: Situation) -> np.ndarray:
        """The feature vector for this step, computed once per (step, history size)."""
        current = situation.session_prefix[-1]
        key = (current.session_id, current.step, len(situation.history))
        if key not in self._features:
            self._features[key] = featurise(situation, hubs=self.hubs)
        return self._features[key]


@dataclass(frozen=True)
class History:
    """What was known before the replay started, or has been learned since.

    Finished sessions' filtered pain points, plus the records those points
    cite, which are the only things worth recalling.
    """

    pain_points: tuple[PainPoint, ...]
    candidates: tuple[Record, ...]
    signatures_at: Mapping[RecordRef, frozenset[Signature]]

    @classmethod
    def empty(cls) -> "History":
        """Nothing known yet."""
        return cls((), (), {})

    @classmethod
    def from_sessions(cls, sessions: Sequence[Sequence[Record]], ctx: ReplayContext) -> "History":
        """The history after learning from `sessions` in order."""
        history = cls.empty()
        for s in sessions:
            history = history.after(s, ctx)
        return history

    def after(self, session: Sequence[Record], ctx: ReplayContext) -> "History":
        """This history plus one finished session's pain points and cited records."""
        points = ctx.labels(session)
        by_ref = {(r.session_id, r.step): r for r in session}
        cited = sorted({ref for p in points for ref in p.record_refs})
        signatures = dict(self.signatures_at)
        for p in points:
            for ref in p.record_refs:
                signatures[ref] = signatures.get(ref, frozenset()) | {p.signature}
        return History(
            self.pain_points + tuple(points),
            self.candidates + tuple(by_ref[ref] for ref in cited),
            signatures,
        )


@dataclass(frozen=True)
class SessionScores:
    """Per-step flags and labels of one replayed session."""

    task_id: str
    followed: tuple[bool, ...]  # label per step
    flagged: tuple[bool, ...]
    recalled: tuple[bool, ...]  # did the decider recall anything at this step
    recall_hit: tuple[bool | None, ...]  # None where no pain point follows


@dataclass(frozen=True)
class OfflineScores:
    """One decider's per-session scores, with the aggregate metrics the table prints."""

    decider: str
    per_session: tuple[SessionScores, ...]

    @property
    def auroc(self) -> float:
        """Balanced accuracy of the flag over every step."""
        return auroc(
            [f for s in self.per_session for f in s.followed],
            [f for s in self.per_session for f in s.flagged],
        )

    @property
    def recall_at_3(self) -> float | None:
        """Recall hit rate, or None for a decider that never recalled anything."""
        if not any(r for s in self.per_session for r in s.recalled):
            return None
        hits = [h for s in self.per_session for h in s.recall_hit if h is not None]
        return sum(hits) / len(hits) if hits else None

    @property
    def n_steps(self) -> int:
        """Steps scored across all sessions."""
        return sum(len(s.followed) for s in self.per_session)


class Replay(NamedTuple):
    """One replay's outcome: scores for the sessions it was given, plus where to resume."""

    scores: OfflineScores  # for the sessions given to this call only
    state: Any  # the learner's state after the last session
    history: History  # history including the sessions given to this call

    def resume(self) -> "Start":
        """The starting point that continues online where this replay stopped."""
        return Start(self.history, self.state)


@dataclass(frozen=True)
class Start:
    """What a replay begins with: the history known so far and the learner's state.

    `state=None` means a fresh learner; a history without a state replays a
    new learner against already-known history.
    """

    history: History
    state: Any = None

    @classmethod
    def fresh(cls) -> "Start":
        """No history and a fresh learner."""
        return cls(History.empty())


def replay(
    decider: Decider,
    sessions: Sequence[Sequence[Record]],
    start: Start,
    *,
    ctx: ReplayContext,
    seed: int,
) -> Replay:
    """Score `decider` on `sessions`, learning after each session ends.

    Raises ValueError for a session without a task id. Pass `Replay.resume()`
    of an earlier call to continue online where it left off.
    """
    history = start.history
    state = decider.initial_state(seed) if start.state is None else start.state
    scored = []
    for session in sessions:
        if not session[0].task_id:
            raise ValueError(f"session {session[0].session_id} has no task id; drop_taskless first")
        targets = _next_pain_points(ctx.labels(session), len(session))
        situations = _situations(session, history)
        decisions, learned = _decide_session(decider, state, situations, targets, ctx)
        scored.append(_session_scores(session, targets, decisions, history))
        for features, outcome in learned:
            state = decider.learn(features, outcome, state)
        history = history.after(session, ctx)
    return Replay(OfflineScores(decider.name, tuple(scored)), state, history)


def drop_taskless(sessions: Sequence[Sequence[Record]]) -> tuple[list[Sequence[Record]], int]:
    """Drop sessions with no task id, which cannot be split or bootstrapped by task.

    The count is logged, never silent.
    """
    kept = [s for s in sessions if s[0].task_id]
    dropped = len(sessions) - len(kept)
    if dropped:
        log.warning("dropped %d session(s) with no task id", dropped)
    return kept, dropped


def _next_pain_points(points: Sequence[PainPoint], n_steps: int) -> list[PainPoint | None]:
    """For each step t, the first pain point at steps t+1..t+WINDOW (ties by signature text)."""
    ordered = sorted(points, key=lambda pt: (pt.step, pt.signature.signal.value, pt.signature.key))
    return [next((pt for pt in ordered if t < pt.step <= t + WINDOW), None) for t in range(n_steps)]


def _situations(session: Sequence[Record], history: History) -> list[Situation]:
    """The situation at each step: the session so far, and only finished sessions' history."""
    return [
        Situation(
            session[0].project, tuple(session[: t + 1]), history.pain_points, history.candidates
        )
        for t in range(len(session))
    ]


def _decide_session(
    decider: Decider,
    state: Any,
    situations: Sequence[Situation],
    targets: Sequence[PainPoint | None],
    ctx: ReplayContext,
) -> tuple[list[Decision], list[tuple[np.ndarray, Outcome]]]:
    decisions, learned = [], []
    for situation, target in zip(situations, targets, strict=True):
        features = ctx.features(situation)
        decisions.append(decider.decide(features, situation, state))
        learned.append((features, _outcome(target)))
    return decisions, learned


def _outcome(target: PainPoint | None) -> Outcome:
    if target is None:
        return Outcome(pain_point_followed=False, signature=None)
    return Outcome(
        pain_point_followed=True,
        signature=target.signature,
        session_id=target.session_id,
        step=target.step,
    )


def _session_scores(
    session: Sequence[Record],
    targets: Sequence[PainPoint | None],
    decisions: Sequence[Decision],
    history: History,
) -> SessionScores:
    def hit(decision: Decision, target: PainPoint | None) -> bool | None:
        if target is None:
            return None
        return any(
            target.signature in history.signatures_at.get((r.session_id, r.step), frozenset())
            for r in decision.recall[:RECALL_SIZE]
        )

    return SessionScores(
        task_id=session[0].task_id or "",  # replay() has already refused task-less sessions
        followed=tuple(t is not None for t in targets),
        flagged=tuple(d.trouble is not None for d in decisions),
        recalled=tuple(bool(d.recall) for d in decisions),
        recall_hit=tuple(hit(d, t) for d, t in zip(decisions, targets, strict=True)),
    )


def auroc(followed: Sequence[bool], flagged: Sequence[bool]) -> float:
    """AUROC of a binary flag, ties as half: (TPR + TNR) / 2."""
    positives, negatives = sum(followed), len(followed) - sum(followed)
    if positives == 0 or negatives == 0:
        raise ValueError("AUROC needs steps both followed and not followed by a pain point")
    tp = sum(a and b for a, b in zip(followed, flagged, strict=True))
    tn = sum((not a) and (not b) for a, b in zip(followed, flagged, strict=True))
    return (tp / positives + tn / negatives) / 2


def hub_modules(references: Mapping[str, frozenset[str]], cutoff: float) -> frozenset[str]:
    """Modules directly referenced by more than `cutoff` of the repo's test files.

    Breaking one of them says nothing about the edit that came before.
    """
    tests = {p for refs in references.values() for p in refs if _is_test(p)} | {
        p for p in references if _is_test(p)
    }
    if not tests:
        return frozenset()
    return frozenset(
        module
        for module, refs in references.items()
        if not _is_test(module) and len(refs & tests) / len(tests) > cutoff
    )


def _is_test(path: str) -> bool:
    return path.rsplit("/", 1)[-1].startswith("test_")


def split_by_task(
    task_ids: Sequence[str], *, test_fraction: float, seed: int
) -> tuple[frozenset[str], frozenset[str]]:
    """Train and test task ids; a seeded `test_fraction` of the distinct ids is held out."""
    ordered = sorted(set(task_ids))
    n_test = round(len(ordered) * test_fraction)
    test = frozenset(random.Random(seed).sample(ordered, n_test))
    return frozenset(ordered) - test, test
