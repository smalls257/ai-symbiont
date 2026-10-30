"""Precision, recall and net benefit at a warning budget, on synthetic steps.

Violation prevented: **Paper Tiger**. A wrong warning must cost something in
the table, or a learner that warns on everything looks as good as one that
speaks only when it is right.
"""

from dataclasses import replace

import numpy as np
import pytest

from record_builders import edit, run, say, session, view
from symbiont.core.counters import Counters
from symbiont.eval.offline import ReplayContext, Start, replay
from symbiont.eval.warning_budget_metrics import (
    RiskRecorder,
    RiskTrace,
    bootstrap_draws,
    budget_row,
    counts_by_task,
    metrics_of,
    risk_traces,
)

TEST_FILE = "tests/test_tokens.py"


def trap_session(sid, task):
    records = session(
        view(TEST_FILE),
        edit("sqlglot/parser.py"),
        run(f"python -m pytest {TEST_FILE} -q", 1, "ImportError: cannot import name 'x'"),
        *[say("done") for _ in range(7)],
    )
    return [replace(r, session_id=sid, task_id=task) for r in records]


def test_arithmetic_on_known_counts():
    # tp=10 fp=30 fn=10 tn=50 over 100 steps
    m = metrics_of(np.array([[10.0, 30.0, 10.0, 50.0]]))
    assert m["precision"][0] == pytest.approx(0.25)
    assert m["recall"][0] == pytest.approx(0.5)
    assert m["flag_rate"][0] == pytest.approx(0.4)
    assert m["net_benefit_per_100_c0.5"][0] == pytest.approx(-5.0)
    assert m["net_benefit_per_100_c1"][0] == pytest.approx(-20.0)
    assert m["net_benefit_per_100_c2"][0] == pytest.approx(-50.0)


def test_no_warnings_means_undefined_precision_and_zero_net_benefit():
    m = metrics_of(np.array([[0.0, 0.0, 10.0, 90.0]]))
    assert np.isnan(m["precision"][0])
    assert m["recall"][0] == 0.0
    assert m["net_benefit_per_100_c1"][0] == 0.0


def test_counts_are_per_task_and_use_at_or_above_the_threshold():
    traces = (
        RiskTrace("a", (True, False, True), (3.0, 3.0, 1.0)),
        RiskTrace("a", (False,), (0.0,)),
        RiskTrace("b", (True, False), (2.0, 0.0)),
    )
    counts = counts_by_task(traces, threshold=2.0, tasks=["a", "b"])
    # task a: flagged steps 0,1 -> tp 1 fp 1; step 2 missed -> fn 1; last tn 1
    assert counts[0].tolist() == [1, 1, 1, 1]
    assert counts[1].tolist() == [1, 0, 0, 1]


def test_a_missing_risk_in_a_trace_raises():
    traces = (RiskTrace("a", (True,), (None,)),)
    with pytest.raises(ValueError):
        counts_by_task(traces, threshold=1.0, tasks=["a"])


def test_recorder_lines_each_risk_up_with_its_step_through_a_real_replay():
    recorder = RiskRecorder(Counters(min_count=1))
    sessions = [trap_session(f"h{i}", f"t{i}") for i in range(3)]
    result = replay(recorder, sessions, Start.fresh(), ctx=ReplayContext({}, frozenset()), seed=0)
    traces = risk_traces(result.scores, recorder)
    assert [t.task_id for t in traces] == ["t0", "t1", "t2"]
    assert all(len(t.risk) == len(t.followed) == 10 for t in traces)
    assert traces[0].risk[2] == 0.0, "nothing was known before the first session"
    assert traces[2].risk[2] > 0.0, "the run of the tests file now matches earlier failures"
    assert recorder.name == "counters"


def test_risk_traces_refuse_a_recorder_that_saw_a_different_number_of_steps():
    recorder = RiskRecorder(Counters())
    result = replay(
        recorder,
        [trap_session("h0", "t0")],
        Start.fresh(),
        ctx=ReplayContext({}, frozenset()),
        seed=0,
    )
    recorder.risks.pop()
    with pytest.raises(ValueError):
        risk_traces(result.scores, recorder)


def test_bootstrap_draws_are_reproducible_and_resample_every_task():
    first = bootstrap_draws(5, seed=7, n_boot=50)
    assert np.array_equal(first, bootstrap_draws(5, seed=7, n_boot=50))
    assert first.shape == (50, 5) and (first.sum(axis=1) == 5).all()


def test_row_interval_contains_the_point_and_reports_undefined_draws():
    rng = np.random.default_rng(0)
    counts = np.column_stack(
        [
            rng.integers(0, 4, 40),
            rng.integers(0, 8, 40),
            rng.integers(0, 4, 40),
            rng.integers(10, 20, 40),
        ]
    ).astype(float)
    row = budget_row(counts, bootstrap_draws(40, seed=1, n_boot=300))
    p = row["precision"]
    assert p["ci95_low"] <= p["value"] <= p["ci95_high"]
    assert row["precision"]["undefined_draws"] == 0
    none_flagged = np.zeros((40, 4))
    none_flagged[:, 2:] = 5
    empty = budget_row(none_flagged, bootstrap_draws(40, seed=1, n_boot=300))
    assert empty["precision"]["undefined_draws"] == 300 and empty["precision"]["value"] is None
