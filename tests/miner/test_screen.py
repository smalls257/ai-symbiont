"""Screening: a lesson needs a shown fix; every held group is counted under one reason."""

from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.screen import HoldReason, ScreenRules, screen

TRAP = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_x.py", "ImportError"))


def lesson(signature=TRAP, session="s1", fix=FixKind.CODE_FIX):
    pain = PainPoint(signature, session, 1, ((session, 1),))
    return Lesson(
        pain_point=pain,
        quote="q",
        resolution=("ran `x`",) if fix else (),
        unresolved_because=None if fix else "no later command",
        remote_safe=True,
        sources=((session, 1),),
        fix=fix,
    )


def test_a_group_with_no_fix_shown_is_struggle_not_a_lesson():
    lessons = [lesson(session="s1", fix=None), lesson(session="s2", fix=None)]
    result = screen(lessons, ScreenRules())
    assert result.kept == [] and result.held == {HoldReason.NO_FIX_SHOWN: 1}
    assert result.struggle == lessons


def test_a_fixed_trap_seen_in_two_sessions_is_kept():
    lessons = [lesson(session="s1"), lesson(session="s2", fix=None)]
    result = screen(lessons, ScreenRules())
    assert result.kept == lessons and result.held == {} and result.struggle == []


def test_a_fixed_trap_in_one_session_is_held_as_too_few_sessions():
    result = screen([lesson(), lesson()], ScreenRules())
    assert result.kept == [] and result.held == {HoldReason.TOO_FEW_SESSIONS: 1}


def test_min_sessions_one_keeps_single_session_traps():
    result = screen([lesson()], ScreenRules(min_sessions=1))
    assert len(result.kept) == 1 and result.held == {}


def test_a_single_user_correction_is_never_held():
    correction = Signature(Signal.CORRECTION, ("", "use uv"))
    review = Signature(Signal.REVIEW_FLAG, ("a.py",))
    lessons = [lesson(correction, fix=None), lesson(review, fix=None)]
    result = screen(lessons, ScreenRules(min_sessions=5))
    assert result.kept == lessons and result.held == {}


def test_each_group_is_counted_once_under_the_first_reason_that_applies():
    bare = Signature(Signal.FAILED_COMMAND, ("make", "lint", "exit 2"))
    probe = Signature(Signal.FAILED_COMMAND, ("grep", "a.py", "ImportError"))
    lessons = [
        lesson(bare, "s1", fix=FixKind.CODE_FIX),  # no message beats too few sessions
        lesson(probe, "s1", fix=FixKind.CODE_FIX),  # a probe beats too few sessions
        lesson(TRAP, "s1", fix=None),  # no fix shown
        lesson(TRAP, "s2", fix=None),
    ]
    result = screen(lessons, ScreenRules())
    assert result.held == {
        HoldReason.NO_MESSAGE: 1,
        HoldReason.PROBE_COMMAND: 1,
        HoldReason.NO_FIX_SHOWN: 1,
    }
    assert result.kept == []


def test_an_ignored_group_is_counted_as_ignored_and_its_lessons_are_still_kept():
    """Failure guarded against: dropping ignored lessons, so Restore after a re-mine finds none."""
    ignored = Signature(Signal.FAILED_COMMAND, ("make", "lint", "exit 2 NameError"))
    lessons = [
        lesson(ignored, "s1", fix=FixKind.CODE_FIX),
        lesson(ignored, "s2", fix=FixKind.CODE_FIX),
    ]
    result = screen(lessons, ScreenRules(ignored=frozenset({ignored})))
    assert result.held == {HoldReason.IGNORED: 1}
    assert result.kept == lessons


def test_an_ignored_group_that_another_reason_holds_is_counted_under_that_reason():
    ignored = Signature(Signal.FAILED_COMMAND, ("make", "-", "exit 2"))
    result = screen([lesson(ignored, fix=None)], ScreenRules(ignored=frozenset({ignored})))
    assert result.held == {HoldReason.NO_FIX_SHOWN: 1}
