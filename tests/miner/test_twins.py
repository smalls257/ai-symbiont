"""Twins (same failed command and error line) merge into one lesson that lists every fix."""

from dataclasses import replace

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.twins import merge_twins

FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "t.py", "ImportError"))


def lesson(step, fix, signature=FAILED, spark_safe=True):
    pain = PainPoint(signature, "s", step, (("s", step),))
    resolution = (fix,) if fix else ()
    return Lesson(pain, "q", resolution, None if fix else "none", spark_safe, (("s", step),))


def test_twins_pool_their_fixes_in_first_seen_order_without_repeats():
    merged = merge_twins([lesson(1, "ran a"), lesson(2, "ran b"), lesson(3, "ran a")])
    assert len(merged) == 1 and merged[0].resolution == ("ran a", "ran b")
    assert merged[0].sources == (("s", 1), ("s", 2), ("s", 3))


def test_a_twin_with_a_fix_resolves_an_unresolved_first_and_privacy_takes_the_stricter():
    merged = merge_twins([lesson(1, None), lesson(2, "ran b", spark_safe=False)])
    assert merged[0].unresolved_because is None and merged[0].spark_safe is False


def test_different_errors_and_other_signals_stay_apart():
    other = Signature(Signal.FAILED_COMMAND, ("pytest", "t.py", "KeyError"))
    correction = replace(FAILED, signal=Signal.CORRECTION)
    lessons = [lesson(1, "a"), lesson(2, "b", other), lesson(3, "c", correction)]
    assert merge_twins(lessons) == lessons
