import numpy as np
import pytest

from record_builders import run, session, user
from symbiont.core.features import N_FEATURES, featurise
from symbiont.core.slot import Outcome, Situation
from symbiont.core.warner import (
    LOOKS_ROUTINE,
    NOT_A_PAUSE,
    LogisticWarner,
    WarnerWeights,
    WarnerWeightsError,
    warner_risk,
    weights_from,
)
from symbiont.miner.painpoint import Signal


def weights(intercept, note_at=0.5):
    coef = np.zeros(N_FEATURES + 1)
    coef[0] = intercept
    return WarnerWeights(np.zeros(N_FEATURES), np.ones(N_FEATURES), coef, note_at)


def situation(*records):
    return Situation("demo", tuple(session(*records)), (), ())


FAILING = (user("fix it"), run("pytest tests/test_x.py", 1, "ImportError: no x"))


def decide(warner, situation_):
    return warner.decide(featurise(situation_), situation_, warner.initial_state(0))


def test_a_risky_boundary_names_the_steps_trouble_and_no_score():
    decision = decide(LogisticWarner(weights(5.0)), situation(*FAILING))
    assert decision.trouble.signal is Signal.FAILED_COMMAND
    assert decision.why == () and decision.recall == ()
    assert decision.risk > 0.99 and "0.99" not in repr(decision)


def test_a_calm_boundary_stays_quiet_and_says_why():
    decision = decide(LogisticWarner(weights(-5.0)), situation(*FAILING))
    assert (decision.trouble, decision.reason_none) == (None, LOOKS_ROUTINE)


def test_a_risky_step_that_is_not_a_pause_stays_quiet():
    decision = decide(LogisticWarner(weights(5.0)), situation(user("hi"), run("ls", 0)))
    assert (decision.trouble, decision.reason_none) == (None, NOT_A_PAUSE)


def test_learning_is_offline_so_state_is_unchanged():
    warner = LogisticWarner(weights(0.0))
    outcome = Outcome(pain_point_followed=True, signature=None)
    assert warner.learn(np.zeros(N_FEATURES), outcome, "state") == "state"


def test_risk_is_the_logistic_of_the_standardized_features():
    coef = np.zeros(N_FEATURES + 1)
    coef[1] = 2.0
    mean, scale = np.zeros(N_FEATURES), np.full(N_FEATURES, 2.0)
    x = np.zeros(N_FEATURES)
    x[0] = 1.0
    risk = warner_risk(WarnerWeights(mean, scale, coef, 0.5), x)
    assert risk == pytest.approx(1 / (1 + np.exp(-1.0)))


def test_weights_from_a_decoded_file():
    document = {
        "mean": [0.0] * N_FEATURES,
        "scale": [1.0] * N_FEATURES,
        "coef": [0.0] * (N_FEATURES + 1),
        "note_at": 0.3,
    }
    assert weights_from(document).note_at == 0.3


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"coef": [0.0] * N_FEATURES}, "coef must hold 87"),
        ({"scale": [0.0] * N_FEATURES}, "scale must be positive"),
        ({"note_at": 1.0}, "note_at must lie in"),
        ({"mean": [float("nan")] * N_FEATURES}, "not finite"),
        ({"note_at": None}, "misshapes"),
    ],
)
def test_bad_weights_raise_naming_the_field(change, says):
    document = {
        "mean": [0.0] * N_FEATURES,
        "scale": [1.0] * N_FEATURES,
        "coef": [0.0] * (N_FEATURES + 1),
        "note_at": 0.3,
    } | change
    with pytest.raises(WarnerWeightsError, match=says):
        weights_from(document)


def test_a_missing_field_raises():
    with pytest.raises(WarnerWeightsError, match="note_at"):
        weights_from({"mean": [], "scale": [], "coef": []})
