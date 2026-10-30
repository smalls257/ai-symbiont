import pytest

from symbiont.core.slot import Decision, Outcome
from symbiont.miner.painpoint import Signal, Signature


def test_decision_none_has_reason():
    with pytest.raises(ValueError, match="reason_none"):
        Decision(trouble=None, why=(), recall=(), reason_none=None)
    quiet = Decision(
        trouble=None, why=(), recall=(), reason_none="nothing like this has gone wrong here"
    )
    assert quiet.reason_none


def test_decision_with_trouble_needs_no_reason():
    sig = Signature(Signal.LOOP, ("pytest", "t"))
    assert Decision(trouble=sig, why=(), recall=(), reason_none=None).trouble == sig


def test_outcome_carries_what_followed():
    assert Outcome(pain_point_followed=False, signature=None).signature is None
