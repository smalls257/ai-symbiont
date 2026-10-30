"""The indexed learners must decide exactly as a plain scan of history would.

The scans below are the old implementations, kept as oracles only. A random
but seeded stream of sessions is fed through both, step by step, with online
learning after each session, and every Decision must be equal.
"""

import math
import random
from collections import Counter
from dataclasses import replace

import numpy as np

from record_builders import edit, run, say, session, view
from symbiont.core.counters import Counters, _as_pain_point, _each_event_once, _normalised, _quiet
from symbiont.core.features import featurise, meaningful_history
from symbiont.core.indexes import tokens
from symbiont.core.mushroom import Mushroom, _exact_score, kc_code
from symbiont.core.similarity import RECALL_SIZE, Similarity
from symbiont.core.similarity import _quiet as _quiet_similarity
from symbiont.core.slot import NO_HISTORY, Decision, Outcome, Situation
from symbiont.miner.commands import normalise_command
from symbiont.miner.mine import mine_session
from symbiont.miner.painpoint import Signal, Signature

COMMANDS = [
    "pytest tests/test_a.py -q",
    "python -m pytest tests/test_b.py",
    "ls src",
    "grep foo a.py",
    "python run.py",
]
FILES = ["a.py", "b.py", "tests/test_a.py", "tests/test_b.py", "c.py"]


def stream(seed: int, n_sessions: int = 24, length: int = 12):
    rng = random.Random(seed)
    sessions = []
    for s in range(n_sessions):
        records = []
        for _ in range(length):
            kind = rng.choice(["run", "run", "view", "edit", "say"])
            if kind == "run":
                failed = rng.random() < 0.5
                records.append(
                    run(rng.choice(COMMANDS), 1 if failed else 0, "ImportError" if failed else "ok")
                )
            elif kind == "view":
                records.append(view(rng.choice(FILES)))
            elif kind == "edit":
                records.append(
                    edit(rng.choice(FILES), diff=f"-{rng.randint(0, 3)}\n+{rng.randint(0, 3)}\n")
                )
            else:
                records.append(say("hm"))
        sessions.append(
            [replace(r, session_id=f"s{s}", task_id=f"t{s}") for r in session(*records)]
        )
    return sessions


def walk(deciders, seed):
    """Yield the decisions of every decider at every step; learn after each session."""
    sessions = stream(seed)
    history, candidates = [], []
    states = [d.initial_state(0) for d in deciders]
    rng = random.Random(seed + 1)
    for records in sessions:
        outcomes = []
        for t in range(len(records)):
            # the session's own records are offered too: steps at or after t are not the past
            situation = Situation(
                "p", tuple(records[: t + 1]), tuple(history), tuple(candidates) + tuple(records)
            )
            x = featurise(situation)
            yield [d.decide(x, situation, st) for d, st in zip(deciders, states, strict=True)]
            points = mine_session(records, {})
            pain = rng.choice(points) if points and rng.random() < 0.6 else None
            outcome = Outcome(
                pain is not None,
                pain.signature if pain else None,
                records[0].session_id,
                pain.step if pain else None,
            )
            if rng.random() < 0.3:  # trouble the miner never saw, so the learned tally matters
                invented = Signature(
                    Signal.FAILED_COMMAND,
                    ("pytest", rng.choice(FILES), rng.choice(["XError", "YError"])),
                )
                outcome = Outcome(True, invented, f"x{rng.randint(0, 40)}", rng.randint(0, 30))
            outcomes.append((x, outcome))
        for x, outcome in outcomes:
            states = [d.learn(x, outcome, st) for d, st in zip(deciders, states, strict=True)]
        points = mine_session(records, {})
        history += points
        by_ref = {(r.session_id, r.step): r for r in records}
        candidates += [by_ref[ref] for ref in sorted({r for p in points for r in p.record_refs})]


class ScanCounters(Counters):
    """The old decide: scan all of history and every learned event."""

    def decide(self, x, situation, state):
        learned = state or frozenset()
        if not situation.history and not learned:
            return _quiet(NO_HISTORY)
        current = situation.session_prefix[-1] if situation.session_prefix else None
        if current is None:
            return _quiet("the session has not started")
        ordered = sorted(learned, key=lambda e: (e[0], e[1], e[2].signal.value, e[2].key))
        known = replace(
            situation, history=situation.history + tuple(_as_pain_point(e) for e in ordered)
        )
        command = _normalised(current)
        past = _each_event_once(
            p
            for p in meaningful_history(known, self._hubs, self._scratch)
            if self._concerns(p, current, command)
        )
        risk = float(len(past))
        if not past:
            return _quiet("nothing has gone wrong on this file or command before", risk=risk)
        seen = Counter(p.signature for p in past)
        worst = min(seen, key=lambda sig: (-seen[sig], sig.signal.value, sig.key))
        if seen[worst] < self.min_count:
            return _quiet(
                "this file or command has not gone wrong often enough to worry about", risk=risk
            )
        return Decision(worst, tuple(p for p in past if p.signature == worst), (), None, risk=risk)

    @staticmethod
    def _concerns(p, current, command):
        sig = p.signature
        if any(path in sig.key for path in current.files):
            return True
        if sig.signal == Signal.FAILED_COMMAND and current.command:
            return sig.key[:2] == tuple(normalise_command(current.command))
        return False


class ScanSimilarity(Similarity):
    """The old BM25 over every candidate (terms added in sorted order)."""

    def decide(self, x, situation, state):
        if not situation.history and not situation.candidates:
            return _quiet_similarity(NO_HISTORY)
        if not situation.session_prefix:
            return _quiet_similarity("the session has not started")
        current = situation.session_prefix[-1]
        pool = [
            c
            for c in situation.candidates
            if not (c.session_id == current.session_id and c.step >= current.step)
        ]
        recalled = _closest(set(tokens(current)), pool)
        if not recalled:
            return _quiet_similarity("nothing in past work resembles this step")
        return Decision(None, (), recalled, None)


def _closest(query, candidates):
    if not candidates:
        return ()
    docs = [tokens(c) for c in candidates]
    scores = _bm25(query, docs)
    ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: (-scores[i], i))
    return tuple(candidates[i] for i in ranked[:RECALL_SIZE])


def _bm25(query, docs):
    k1, b = 1.5, 0.75
    n = len(docs)
    average = (sum(map(len, docs)) / n) or 1.0
    holding = Counter(t for d in docs for t in set(d))
    scores = []
    for doc in docs:
        counts = Counter(doc)
        score = 0.0
        for term in sorted(query & counts.keys()):
            idf = math.log(1 + (n - holding[term] + 0.5) / (holding[term] + 0.5))
            tf = counts[term]
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(doc) / average))
        scores.append(score)
    return scores


class ScanMushroom(Mushroom):
    """The old recall: featurise and code every candidate sharing a word, every step."""

    def _kind_of_trouble(self, code, situation, state):
        overlaps = {sig: int((mask & code).sum()) for sig, mask in state.learned}
        overlaps = {sig: n for sig, n in overlaps.items() if n > 0}
        if not overlaps:
            return None, ()
        best = min(overlaps, key=lambda sig: (-overlaps[sig], sig.signal.value, sig.key))
        past = meaningful_history(situation, self._hubs, self._scratch)
        return best, tuple(p for p in past if p.signature == best)

    def _recall(self, code, situation, state):
        current = situation.session_prefix[-1]
        words = set(tokens(current))
        earlier = [
            c
            for c in situation.candidates
            if not (c.session_id == current.session_id and c.step >= current.step)
            and words & set(tokens(c))
        ]
        scored = []
        for i, c in enumerate(earlier):
            context = Situation(situation.project, (c,), (), ())
            theirs = kc_code(featurise(context, hubs=self._hubs, scratch=self._scratch), state)
            scored.append(
                (_exact_score(code, np.flatnonzero(theirs).astype(np.int16), state.w_out), i)
            )
        ranked = sorted(((s, i) for s, i in scored if s > 0), key=lambda si: (-si[0], si[1]))
        return tuple(earlier[i] for _, i in ranked[:RECALL_SIZE])


def _all_equal(make_pair, seed):
    steps = list(walk(make_pair(), seed))
    assert all(indexed == scanned for indexed, scanned in steps)
    return [d for pair in steps for d in pair[:1]]


def test_indexed_counters_decide_as_the_scan_does():
    decisions = _all_equal(lambda: [Counters(min_count=2), ScanCounters(min_count=2)], seed=3)
    assert any(d.trouble for d in decisions), "the stream must exercise flags"
    assert any(d.reason_none for d in decisions)


def test_indexed_similarity_decides_as_the_scan_does():
    decisions = _all_equal(lambda: [Similarity(), ScanSimilarity()], seed=4)
    assert any(len(d.recall) == RECALL_SIZE for d in decisions), "the stream must exercise recall"


def test_cached_mushroom_decides_as_the_uncached_path_does():
    decisions = _all_equal(
        lambda: [
            Mushroom(seed=0, trouble_threshold=0.9),
            ScanMushroom(seed=0, trouble_threshold=0.9),
        ],
        seed=5,
    )
    assert any(d.recall for d in decisions) and any(d.trouble for d in decisions)
