import numpy as np

from record_builders import edit, run, session, view
from symbiont.core.counters import Counters
from symbiont.core.slot import Outcome, Situation
from symbiont.miner.painpoint import PainPoint, Signal, Signature

X = np.zeros(86, dtype=np.float32)
FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_tokens.py", "ImportError"))


def situation(records, history=()):
    return Situation(
        project="tobymao/sqlglot",
        session_prefix=tuple(session(*records)),
        history=tuple(history),
        candidates=(),
    )


def pain(signature, step=0, session_id="s0"):
    return PainPoint(signature, session_id, step, ((session_id, step),))


def retry_tests():
    return [run("cd repo && python -m pytest tests/test_tokens.py -q")]


def test_counters_flag_after_two_prior_failures():
    c = Counters()
    history = [pain(FAILED, step=3), pain(FAILED, step=9)]
    d = c.decide(X, situation(retry_tests(), history), c.initial_state(0))
    assert d.trouble == FAILED
    assert d.why == tuple(history)


def test_counters_stay_quiet_after_one_failure_and_say_why():
    c = Counters()
    d = c.decide(X, situation(retry_tests(), [pain(FAILED)]), c.initial_state(0))
    assert d.trouble is None
    assert d.reason_none


def test_min_count_is_configurable():
    c = Counters(min_count=1)
    assert (
        c.decide(X, situation(retry_tests(), [pain(FAILED)]), c.initial_state(0)).trouble == FAILED
    )


def test_counters_flag_a_file_with_repeated_trouble():
    sig = Signature(Signal.REWORKED_EDIT, ("sqlglot/tokens.py",))
    c = Counters()
    d = c.decide(X, situation([edit("sqlglot/tokens.py")], [pain(sig, 1), pain(sig, 2)]), None)
    assert d.trouble == sig


def test_trouble_elsewhere_does_not_count():
    other = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_other.py", "ImportError"))
    c = Counters()
    d = c.decide(X, situation(retry_tests(), [pain(other), pain(other)]), None)
    assert d.trouble is None


def test_pain_points_at_or_after_the_current_step_are_not_history():
    c = Counters()
    # the current step is index 0 of this session; both points are not strictly before it
    d = c.decide(X, situation(retry_tests(), [pain(FAILED, 0, "s1"), pain(FAILED, 5, "s1")]), None)
    assert d.trouble is None


def test_rework_of_a_scratch_file_is_not_counted():
    sig = Signature(Signal.REWORKED_EDIT, ("scratch.py",))
    c = Counters(scratch=frozenset({("s0", "scratch.py")}))
    d = c.decide(X, situation([view("scratch.py")], [pain(sig, 1), pain(sig, 2)]), None)
    assert d.trouble is None


def test_hub_blast_radius_is_not_counted():
    sig = Signature(Signal.BLAST_RADIUS, ("sqlglot/tokens.py", "tests/test_hub.py"))
    c = Counters(hubs=frozenset({"tests/test_hub.py"}))
    d = c.decide(X, situation([edit("sqlglot/tokens.py")], [pain(sig, 1), pain(sig, 2)]), None)
    assert d.trouble is None


def test_learn_counts_an_outcome_toward_the_flag():
    c = Counters()
    state = c.initial_state(0)
    once = c.learn(X, Outcome(True, FAILED), state)
    twice = c.learn(X, Outcome(True, FAILED), once)
    assert c.decide(X, situation(retry_tests()), once).trouble is None
    assert c.decide(X, situation(retry_tests()), twice).trouble == FAILED


def test_learn_ignores_an_outcome_with_no_trouble():
    c = Counters()
    state = c.initial_state(0)
    assert c.learn(X, Outcome(False, None), state) == state


def test_counters_learn_returns_new_state_and_leaves_old():
    c = Counters()
    old = c.initial_state(0)
    new = c.learn(X, Outcome(True, FAILED), old)
    assert new is not old
    assert old == c.initial_state(0)
    assert new != old


def test_empty_history_returns_reason():
    c = Counters()
    d = c.decide(X, situation(retry_tests()), c.initial_state(0))
    assert d.reason_none == "no history for this project yet"


def test_one_failure_seen_by_learn_and_by_history_counts_once():
    c = Counters()
    state = c.learn(X, Outcome(True, FAILED, session_id="s0", step=3), c.initial_state(0))
    d = c.decide(X, situation(retry_tests(), [pain(FAILED, step=3)]), state)
    assert d.trouble is None


def test_a_failure_learned_and_a_different_one_in_history_make_two():
    c = Counters()
    state = c.learn(X, Outcome(True, FAILED, session_id="s0", step=3), c.initial_state(0))
    d = c.decide(X, situation(retry_tests(), [pain(FAILED, step=9)]), state)
    assert d.trouble == FAILED


def test_ties_break_the_same_way_whatever_the_order():
    a = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_tokens.py", "ImportError"))
    b = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_tokens.py", "AssertionError"))
    c = Counters()
    one = [pain(a, 1), pain(a, 2), pain(b, 3), pain(b, 4)]
    two = [pain(b, 3), pain(b, 4), pain(a, 1), pain(a, 2)]
    assert c.decide(X, situation(retry_tests(), one), None).trouble == b
    assert c.decide(X, situation(retry_tests(), two), None).trouble == b


def test_normalised_command_matches_a_real_shaped_failed_command_key():
    real = Signature(
        Signal.FAILED_COMMAND, ("pytest", "tests/test_tokens.py", "E   ImportError: no module")
    )
    c = Counters()
    spelled = [
        run(
            "cd /testbed && timeout 60 python -m pytest -x -q "
            "tests/test_tokens.py::test_a 2>&1 | tail -20"
        )
    ]
    d = c.decide(X, situation(spelled, [pain(real, 1), pain(real, 2)]), None)
    assert d.trouble == real
