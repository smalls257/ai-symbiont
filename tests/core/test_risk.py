"""Decision.risk: an evaluation-only score that never reaches a model.

Violation prevented: **Leaky Narrative**. A number a learner computes for the
budget analysis must not seep into notes, reprs or the delivery layers.
"""

from pathlib import Path

import numpy as np

from record_builders import run, session
from symbiont.core.counters import Counters
from symbiont.core.mushroom import N_ACTIVE, Mushroom, kc_code
from symbiont.core.similarity import Similarity
from symbiont.core.slot import Decision, Outcome, Situation
from symbiont.miner.painpoint import PainPoint, Signal, Signature

X = np.zeros(86, dtype=np.float32)
FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_tokens.py", "ImportError"))
SRC = Path(__file__).resolve().parents[2] / "src" / "symbiont"


def situation(history=(), candidates=()):
    records = session(run("cd repo && python -m pytest tests/test_tokens.py -q"))
    return Situation("tobymao/sqlglot", tuple(records), tuple(history), tuple(candidates))


def pain(step):
    return PainPoint(FAILED, "s0", step, (("s0", step),))


def pattern(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).random(86).astype(np.float32)


def test_risk_is_none_by_default_and_hidden_from_repr():
    d = Decision(trouble=FAILED, why=(), recall=(), reason_none=None, risk=0.8734)
    assert d.risk == 0.8734
    assert "0.8734" not in repr(d) and "risk" not in repr(d)
    assert Decision(FAILED, (), (), None).risk is None


def test_counters_risk_is_the_matching_pain_point_count_even_when_quiet():
    c = Counters(min_count=4)
    d = c.decide(X, situation([pain(1), pain(2), pain(3)]), None)
    assert d.trouble is None
    assert d.risk == 3.0


def test_counters_risk_is_zero_with_nothing_matching():
    c = Counters()
    assert c.decide(X, situation([]), None).risk == 0.0


def test_similarity_has_no_risk():
    assert Similarity().decide(X, situation(), None).risk is None


def test_fly_risk_is_one_minus_the_mean_active_output_weight():
    m = Mushroom(seed=0)
    x = pattern(1)
    s = m.learn(x, Outcome(True, FAILED), m.initial_state(0))
    d = m.decide(x, situation([pain(1)]), s)
    expected = 1.0 - float(s.w_out[kc_code(x, s)].sum()) / N_ACTIVE
    assert d.risk == expected and d.risk > 0.05


def test_fly_risk_is_zero_for_an_untouched_pattern():
    m = Mushroom(seed=0)
    assert m.decide(pattern(1), situation([pain(1)]), m.initial_state(0)).risk == 0.0


def test_delivery_and_service_never_read_risk():
    for layer in ("delivery", "service"):
        for source in (SRC / layer).rglob("*.py"):
            assert ".risk" not in source.read_text(), (
                f"{source} reads Decision.risk; notes are prose"
            )
