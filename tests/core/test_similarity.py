from dataclasses import replace

import numpy as np

from record_builders import edit, run, session, view
from symbiont.core.similarity import Similarity
from symbiont.core.slot import Outcome, Situation

X = np.zeros(86, dtype=np.float32)


def situation(records, candidates=()):
    return Situation(
        project="tobymao/sqlglot",
        session_prefix=tuple(session(*records)),
        history=(),
        candidates=tuple(candidates),
    )


def test_similarity_returns_original_records_not_text_copies():
    match = run("pytest tests/test_tokens.py -q", exit_code=1)
    s = Similarity()
    d = s.decide(X, situation([run("pytest tests/test_tokens.py")], [match]), None)
    assert len(d.recall) == 1
    assert d.recall[0] is match


def test_recall_is_the_three_closest_best_first():
    best = run("pytest tests/test_tokens.py -q")
    good = edit("sqlglot/tokens.py")
    weak = run("pytest tests/test_parser.py")
    weaker = run("pytest")
    unrelated = run("ls docs")
    current = [run("pytest tests/test_tokens.py")]
    d = Similarity().decide(X, situation(current, [unrelated, weaker, weak, good, best]), None)
    assert len(d.recall) == 3
    assert d.recall[0] is best
    assert unrelated not in d.recall


def test_files_count_as_well_as_commands():
    target = view("sqlglot/dialects/duckdb.py")
    d = Similarity().decide(
        X, situation([edit("sqlglot/dialects/duckdb.py")], [run("ls docs"), target]), None
    )
    assert d.recall == (target,)


def test_similarity_flags_nothing():
    d = Similarity().decide(X, situation([run("pytest a.py")], [run("pytest a.py")]), None)
    assert d.trouble is None and d.why == ()


def test_empty_history_returns_reason():
    d = Similarity().decide(X, situation([run("pytest a.py")]), None)
    assert d.reason_none == "no history for this project yet"
    assert d.recall == ()


def test_nothing_resembling_it_says_so():
    d = Similarity().decide(X, situation([run("pytest a.py")], [run("ls docs")]), None)
    assert d.recall == ()
    assert d.reason_none and d.reason_none != "no history for this project yet"


def test_learn_leaves_state_alone():
    s = Similarity()
    state = s.initial_state(0)
    assert s.learn(X, Outcome(True, None), state) == state


def test_pain_points_but_no_candidates_says_nothing_resembles_it():
    from symbiont.miner.painpoint import PainPoint, Signal, Signature

    pp = PainPoint(Signature(Signal.LOOP, ("command", "x")), "s0", 1, (("s0", 1),))
    sit = Situation("p", tuple(session(run("pytest a.py"))), (pp,), ())
    d = Similarity().decide(X, sit, None)
    assert d.recall == () and d.reason_none


def test_the_current_step_never_recalls_itself_or_its_future():
    earlier = run("pytest a.py")
    now = run("pytest a.py")
    later = run("pytest a.py")
    recs = session(earlier, now)
    future = session(earlier, now, later)[2]
    other_session = replace(run("pytest a.py"), session_id="s0", step=50)
    sit = Situation("p", tuple(recs), (), (recs[0], recs[1], future, other_session))
    d = Similarity().decide(X, sit, None)
    assert recs[0] in d.recall and other_session in d.recall
    assert recs[1] not in d.recall and future not in d.recall
