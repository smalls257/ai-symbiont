"""The prereg's run rules as pure functions; no data, no network."""

from dataclasses import replace

import pytest

from record_builders import edit, say, session
from symbiont.eval.offline import OfflineScores, SessionScores
from symbiont.eval.selection import (
    group_sessions,
    median_task,
    per_step_bits,
    pick_best,
    replay_order,
    row_summary,
)


def sess(sid, task):
    return [replace(r, session_id=sid, task_id=task) for r in session(edit("a.py"), say("x"))]


def test_replay_order_keeps_a_tasks_attempts_together_and_is_seeded():
    sessions = [sess(f"s{i}-{t}", t) for t in ("a", "b", "c", "d") for i in (2, 1)]
    order = [s[0].session_id for s in replay_order(sessions, seed=7)]
    assert order == [s[0].session_id for s in replay_order(list(reversed(sessions)), seed=7)]
    tasks = [s[0].task_id for s in replay_order(sessions, seed=7)]
    assert all(tasks[i] == tasks[i + 1] for i in (0, 2, 4, 6))
    within = [i for i in order if i.endswith(tasks[0])]
    assert within == sorted(within)


def test_median_task_odd_even_and_ties():
    dates = {"a": "2020", "b": "2021", "c": "2022", "d": "2023"}
    assert median_task(dates, frozenset("abc")) == "b"
    assert median_task(dates, frozenset("abcd")) == "b", (
        "an even count takes the earlier middle one"
    )
    tied = {"x": "2020", "y": "2020", "z": "2020"}
    assert median_task(tied, frozenset("xyz")) == "y"
    assert median_task({"x": "2020", "w": "2020"}, frozenset("xw")) == "w", (
        "equal dates break by instance id"
    )


def test_median_task_refuses_a_missing_date():
    with pytest.raises(ValueError, match="no created_at"):
        median_task({"a": "2020"}, frozenset("ab"))


def test_pick_best_ties_go_to_the_first_listed():
    best, scores = pick_best([3, 1, 2], {3: 0.5, 1: 0.7, 2: 0.7}.__getitem__)
    assert best == 1 and scores == {3: 0.5, 1: 0.7, 2: 0.7}
    assert pick_best([5, 6], lambda v: 0.5)[0] == 5


def test_group_sessions_splits_on_session_id():
    a, b = sess("a", "t"), sess("b", "t")
    assert [len(s) for s in group_sessions(a + b)] == [len(a), len(b)]


def scores(flags):
    per = tuple(
        SessionScores(f"t{i}", f, g, (False,) * len(f), (None,) * len(f))
        for i, (f, g) in enumerate(flags)
    )
    return OfflineScores("x", per)


def test_row_summary_has_interval_flag_rate_and_recall_none_when_never_recalled():
    runs = [scores([((True, False, False, True), (True, False, True, False))] * 20)]
    row = row_summary("reference", runs, seed=1)
    assert row["balanced accuracy (AUROC of the binary flag)"] == 0.5
    assert row["ci95_low"] <= 0.5 <= row["ci95_high"]
    assert row["flag_rate"] == 0.5 and row["recall_at_3"] is None and row["steps"] == 80


def test_per_step_bits_are_one_character_per_step():
    bits = per_step_bits(scores([((True, False), (False, True))]))
    assert bits == [{"task_id": "t0", "followed": "10", "flagged": "01"}]
