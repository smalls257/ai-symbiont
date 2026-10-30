"""Replay's learning must not depend on whether a warning was issued.

Violation prevented: **Paper Tiger** in the budget analysis. The exploratory
run replays each learner once at its G6 setting and reads risk at every step,
which is only valid if the setting (counters minimum count, fly trouble
threshold) changes the flags and nothing else.
"""

from dataclasses import replace

import numpy as np

from record_builders import edit, run, say, session, view
from symbiont.core.counters import Counters
from symbiont.core.mushroom import Mushroom
from symbiont.eval.offline import ReplayContext, Start, replay
from symbiont.eval.warning_budget_metrics import RiskRecorder

TEST_FILE = "tests/test_tokens.py"


def trap_session(sid, task):
    records = session(
        view(TEST_FILE),
        edit("sqlglot/parser.py"),
        run(f"python -m pytest {TEST_FILE} -q", 1, "ImportError: cannot import name 'x'"),
        *[say("done") for _ in range(7)],
    )
    return [replace(r, session_id=sid, task_id=task) for r in records]


def replayed(learner):
    recorder = RiskRecorder(learner)
    sessions = [trap_session(f"h{i}", f"t{i % 3}") for i in range(6)]
    result = replay(recorder, sessions, Start.fresh(), ctx=ReplayContext({}, frozenset()), seed=0)
    return result, recorder.risks


def flags(result):
    return [f for s in result.scores.per_session for f in s.flagged]


def test_counters_learn_and_score_risk_the_same_whatever_the_minimum_count():
    eager, eager_risks = replayed(Counters(min_count=1))
    shy, shy_risks = replayed(Counters(min_count=99))
    assert any(flags(eager)) and not any(flags(shy)), "setup: the settings must change the flags"
    assert eager.state == shy.state
    assert eager_risks == shy_risks


def test_the_fly_learns_and_scores_risk_the_same_whatever_the_trouble_threshold():
    eager, eager_risks = replayed(Mushroom(seed=0, trouble_threshold=0.99))
    shy, shy_risks = replayed(Mushroom(seed=0, trouble_threshold=0.0))
    assert any(flags(eager)) and not any(flags(shy)), "setup: the settings must change the flags"
    assert np.array_equal(eager.state.w_out, shy.state.w_out)
    pairs = zip(eager.state.learned, shy.state.learned, strict=True)
    assert all(a[0] == b[0] and np.array_equal(a[1], b[1]) for a, b in pairs)
    assert eager_risks == shy_risks
