from dataclasses import replace

import numpy as np
import pytest

from record_builders import edit, run, session
from symbiont.core.features import featurise
from symbiont.core.mushroom import (
    N_ACTIVE,
    N_KC,
    Mushroom,
    kc_code,
)
from symbiont.core.slot import NO_HISTORY, Outcome, Situation
from symbiont.miner.painpoint import PainPoint, Signal, Signature

FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_tokens.py", "ImportError"))


def pattern(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).random(86).astype(np.float32)


def situation(records, history=(), candidates=()):
    return Situation(
        project="tobymao/sqlglot",
        session_prefix=tuple(session(*records)),
        history=tuple(history),
        candidates=tuple(candidates),
    )


def pain(step=0):
    return PainPoint(FAILED, "s0", step, (("s0", step),))


def test_exactly_259_active():
    m = Mushroom(seed=1)
    state = m.initial_state(1)
    for seed in range(5):
        code = kc_code(pattern(seed), state)
        assert code.shape == (N_KC,) and code.dtype == bool
        assert code.sum() == N_ACTIVE == 259
    assert kc_code(np.zeros(86, dtype=np.float32), state).sum() == 259


def test_each_kc_listens_to_seven_inputs():
    state = Mushroom(seed=1).initial_state(1)
    assert state.inputs.shape == (5177, 7)
    assert all(len(set(row)) == 7 for row in state.inputs[:200])


def test_seed_reproducible():
    a, b, c = (Mushroom(seed=s).initial_state(s) for s in (3, 3, 4))
    assert np.array_equal(a.inputs, b.inputs)
    assert not np.array_equal(a.inputs, c.inputs)


def test_learn_lowers_score_for_punished_pattern():
    m = Mushroom(seed=0)
    s0 = m.initial_state(0)
    x = pattern(1)
    s1 = m.learn(x, Outcome(True, FAILED), s0)
    assert s1.w_out[kc_code(x, s1)].mean() < s0.w_out[kc_code(x, s0)].mean()


def test_learn_is_pure():
    m = Mushroom(seed=0)
    s0 = m.initial_state(0)
    w, inputs = s0.w_out.copy(), s0.inputs.copy()
    m.learn(pattern(1), Outcome(True, FAILED), s0)
    m.learn(pattern(1), Outcome(False, None), s0)
    assert np.array_equal(s0.w_out, w) and np.array_equal(s0.inputs, inputs)


def test_calm_outcome_recovers_a_depressed_pattern():
    m = Mushroom(seed=0)
    x = pattern(1)
    hurt = m.learn(x, Outcome(True, FAILED), m.initial_state(0))
    healed = m.learn(x, Outcome(False, None), hurt)
    code = kc_code(x, hurt)
    assert healed.w_out[code].mean() > hurt.w_out[code].mean()


def test_unrelated_pattern_barely_moves():
    m = Mushroom(seed=0)
    s0 = m.initial_state(0)
    s = s0
    for _ in range(3):
        s = m.learn(pattern(1), Outcome(True, FAILED), s)
    own = 1 - s.w_out[kc_code(pattern(1), s)].mean()
    other = 1 - s.w_out[kc_code(pattern(2), s)].mean()
    assert own > 0.2
    assert other < own / 4


def test_flywire_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Mushroom(seed=0, wiring="flywire", flywire_path=tmp_path / "nope.npz").initial_state(0)
    with pytest.raises(ValueError):
        Mushroom(seed=0, wiring="flywire", flywire_path=None).initial_state(0)


def test_flywire_malformed_file_raises(tmp_path):
    path = tmp_path / "bad.npz"
    np.savez(path, kc_inputs=np.zeros((10, 7), dtype=int))
    with pytest.raises(ValueError):
        Mushroom(seed=0, wiring="flywire", flywire_path=path).initial_state(0)


def test_flywire_file_is_used(tmp_path):
    inputs = np.tile(np.arange(7), (N_KC, 1)) + (np.arange(N_KC)[:, None] % 70)
    path = tmp_path / "wiring.npz"
    np.savez(path, kc_inputs=inputs)
    state = Mushroom(seed=0, wiring="flywire", flywire_path=path).initial_state(0)
    assert np.array_equal(state.inputs, inputs)


def test_quiet_without_history_says_why():
    m = Mushroom(seed=0)
    d = m.decide(pattern(1), situation([run("pytest a.py")]), m.initial_state(0))
    assert d.trouble is None and d.reason_none == NO_HISTORY


def test_flags_the_kind_of_trouble_after_it_was_punished():
    m = Mushroom(seed=0, trouble_threshold=0.9)
    x = pattern(1)
    s = m.initial_state(0)
    for _ in range(3):
        s = m.learn(x, Outcome(True, FAILED), s)
    d = m.decide(x, situation([run("pytest a.py")], [pain()]), s)
    assert d.trouble == FAILED
    assert d.why == (pain(),)
    assert m.last_activity is not None and m.last_activity.sum() == 259


def test_unpunished_pattern_stays_quiet():
    m = Mushroom(seed=0, trouble_threshold=0.9)
    d = m.decide(pattern(1), situation([run("pytest a.py")], [pain()]), m.initial_state(0))
    assert d.trouble is None and d.reason_none


def test_recall_returns_original_earlier_records_only():
    m = Mushroom(seed=0, trouble_threshold=0.9)
    past = run("pytest tests/test_tokens.py -q", exit_code=1)
    later = run("pytest tests/test_tokens.py -q")
    current = [run("pytest tests/test_tokens.py -q")]
    prefix = session(*current)
    x = featurise(situation(current))
    s = m.initial_state(0)
    cand_x = featurise(Situation("p", (past,), (), ()))
    for _ in range(3):
        s = m.learn(cand_x, Outcome(True, FAILED), s)
    in_session = replace(later, session_id=prefix[-1].session_id, step=prefix[-1].step + 1)
    other = replace(past, session_id="s0", step=4)
    d = m.decide(x, situation(current, [pain()], [other, in_session]), s)
    assert d.recall == (other,)
    assert d.recall[0] is other


def test_empty_candidates_ok():
    m = Mushroom(seed=0)
    d = m.decide(pattern(1), situation([edit("a.py")], [pain()], []), m.initial_state(0))
    assert d.reason_none or d.trouble


OTHER = Signature(Signal.REWORKED_EDIT, ("sqlglot/parser.py", "sqlglot/tokens.py"))


def trained(m, patterns_and_kinds, times=3):
    s = m.initial_state(0)
    for x, kind in patterns_and_kinds:
        for _ in range(times):
            s = m.learn(x, Outcome(True, kind), s)
    return s


def test_each_pattern_names_its_own_trouble():
    m = Mushroom(seed=0, trouble_threshold=0.95)
    a, b = pattern(1), pattern(2)
    s = trained(m, [(a, FAILED), (b, OTHER)])
    # FAILED is the commoner kind in history, so a frequency pick would name it for both.
    history = [pain(0), pain(1), pain(2)]
    sit = situation([run("pytest a.py")], history)
    assert m.decide(a, sit, s).trouble == FAILED
    d = m.decide(b, sit, s)
    assert d.trouble == OTHER


def test_why_is_history_of_the_chosen_kind():
    m = Mushroom(seed=0, trouble_threshold=0.95)
    other_point = PainPoint(OTHER, "s0", 5, (("s0", 5),))
    s = trained(m, [(pattern(1), FAILED), (pattern(2), OTHER)])
    d = m.decide(pattern(2), situation([run("pytest a.py")], [pain(0), other_point]), s)
    assert d.why == (other_point,)


def sparse(*hot: int) -> np.ndarray:
    x = np.zeros(86, dtype=np.float32)
    x[list(hot)] = 1.0
    return x


def test_sparse_input_does_not_collapse_to_lowest_cells():
    state = Mushroom(seed=0).initial_state(0)
    code = kc_code(sparse(3, 40), state)
    assert code.sum() == 259
    drive = sparse(3, 40)[state.inputs].sum(axis=1)
    lowest_index_winners = np.argsort(-drive, kind="stable")[:259]
    assert set(code.nonzero()[0]) != set(lowest_index_winners)


def test_different_sparse_inputs_give_different_codes():
    state = Mushroom(seed=0).initial_state(0)
    assert not np.array_equal(kc_code(sparse(3, 40), state), kc_code(sparse(5, 41), state))
    assert not np.array_equal(
        kc_code(np.zeros(86, dtype=np.float32), state), kc_code(sparse(3), state)
    )


def test_jitter_is_seeded():
    a, b, c = (Mushroom(seed=s).initial_state(0) for s in (1, 1, 2))
    assert np.array_equal(kc_code(sparse(3), a), kc_code(sparse(3), b))
    assert not np.array_equal(kc_code(sparse(3), a), kc_code(sparse(3), c))


def test_one_punishment_sits_on_the_threshold_and_is_not_trouble():
    m = Mushroom(seed=0)  # placeholder 0.9 equals one punishment's score
    x = pattern(1)
    sit = situation([run("pytest a.py")], [pain()])
    once = m.learn(x, Outcome(True, FAILED), m.initial_state(0))
    twice = m.learn(x, Outcome(True, FAILED), once)
    assert m.decide(x, sit, once).trouble is None
    assert m.decide(x, sit, twice).trouble == FAILED


def test_low_score_with_no_recorded_kind_says_so():
    m = Mushroom(seed=0)
    s = m.initial_state(0)
    for _ in range(3):
        s = m.learn(pattern(1), Outcome(True, None), s)
    d = m.decide(pattern(1), situation([run("pytest a.py")], [pain()]), s)
    assert d.trouble is None
    assert d.reason_none and "no kind" in d.reason_none


def test_trained_state_is_not_no_history():
    m = Mushroom(seed=0)
    s = m.learn(pattern(1), Outcome(False, None), m.initial_state(0))
    d = m.decide(pattern(1), situation([run("pytest a.py")]), s)
    assert d.reason_none != NO_HISTORY


def test_session_not_started_says_so():
    m = Mushroom(seed=0)
    d = m.decide(pattern(1), Situation("p", (), (pain(),), ()), m.initial_state(0))
    assert d.reason_none == "the session has not started"


def test_learn_does_not_mutate_learned_masks():
    m = Mushroom(seed=0)
    s1 = trained(m, [(pattern(1), FAILED)], times=1)
    snapshot = s1.learned[0][1].copy()
    m.learn(pattern(2), Outcome(True, FAILED), s1)
    assert np.array_equal(s1.learned[0][1], snapshot)


def _kc_code_by_full_sort(x, state):
    drive = x[state.inputs].sum(axis=1, dtype=np.float64) + state.jitter
    code = np.zeros(N_KC, dtype=bool)
    code[np.argsort(-drive, kind="stable")[:N_ACTIVE]] = True
    return code


def test_kc_code_is_what_a_full_stable_sort_picks():
    m = Mushroom(seed=2)
    state = m.initial_state(0)
    rng = np.random.default_rng(0)
    inputs = [np.zeros(86, dtype=np.float32), np.ones(86, dtype=np.float32)]
    inputs += [rng.integers(0, 2, 86).astype(np.float32) for _ in range(20)]
    for x in inputs:
        assert np.array_equal(kc_code(x, state), _kc_code_by_full_sort(x, state))


def test_kc_code_breaks_exact_ties_towards_the_lower_cell():
    m = Mushroom(seed=2)
    state = replace(m.initial_state(0), jitter=np.zeros(N_KC))  # every cell with equal drive ties
    x = np.zeros(86, dtype=np.float32)
    assert np.array_equal(kc_code(x, state), _kc_code_by_full_sort(x, state))
    assert kc_code(x, state)[:N_ACTIVE].all()
