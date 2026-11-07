"""Screening: a lesson needs a shown fix; every held group is counted under one reason."""

from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.screen import HoldReason, ScreenRules, screen, taught_since_the_fix_rule

TRAP = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_x.py", "ImportError"))


def lesson(signature=TRAP, session="s1", fix=FixKind.CODE_FIX, target_created=False):
    pain = PainPoint(signature, session, 1, ((session, 1),))
    return Lesson(
        pain_point=pain,
        quote="q",
        resolution=("ran `x`",) if fix else (),
        unresolved_because=None if fix else "no later command",
        remote_safe=True,
        sources=((session, 1),),
        fix=fix,
        target_created=target_created,
    )


def test_a_group_with_no_fix_shown_is_struggle_not_a_lesson():
    lessons = [lesson(session="s1", fix=None), lesson(session="s2", fix=None)]
    result = screen(lessons, ScreenRules())
    assert result.kept == [] and result.held == {HoldReason.NO_FIX_SHOWN: 1}
    assert result.struggle == lessons


def test_a_fixed_trap_seen_in_two_sessions_is_kept():
    lessons = [lesson(session="s1"), lesson(session="s2")]
    result = screen(lessons, ScreenRules())
    assert result.kept == lessons and result.held == {} and result.struggle == []


def test_the_fix_itself_must_come_back_in_two_sessions():
    """Failure guarded against: one fixed session plus one unfixed one passing as "seen twice"."""
    lessons = [lesson(session="s1"), lesson(session="s2", fix=None)]
    result = screen(lessons, ScreenRules())
    assert result.kept == [] and result.held == {HoldReason.TOO_FEW_SESSIONS: 1}


def test_a_kept_group_keeps_only_the_occurrences_that_show_the_fix():
    """Failure guarded against: a ready lesson whose card shows an occurrence never fixed."""
    fixed = [lesson(session="s1"), lesson(session="s2")]
    result = screen([*fixed, lesson(session="s3", fix=None)], ScreenRules())
    assert result.kept == fixed and result.held == {} and result.struggle == []


SCRATCH = Signature(Signal.FAILED_COMMAND, ("python", "reproduce_issue.py", "TypeError"))
INLINE = Signature(Signal.FAILED_COMMAND, ("python", "<inline>", "AttributeError"))
MANAGE = Signature(Signal.FAILED_COMMAND, ("python", "manage.py", "OperationalError"))


def test_a_group_on_a_script_the_session_created_is_throwaway():
    """Failure guarded against: every session's own `reproduce_issue.py` merged into one trap."""
    lessons = [lesson(SCRATCH, s, target_created=True) for s in ("s1", "s2", "s3")]
    result = screen(lessons, ScreenRules())
    assert result.kept == [] and result.held == {HoldReason.THROWAWAY_SCRIPT: 1}


def test_manage_py_is_not_throwaway():
    """Failure guarded against: holding a project script because it sits at the top level."""
    lessons = [lesson(MANAGE, s) for s in ("s1", "s2")]
    result = screen(lessons, ScreenRules())
    assert result.kept == lessons and result.held == {}


def test_inline_python_is_throwaway():
    lessons = [lesson(INLINE, s) for s in ("s1", "s2", "s3")]
    result = screen(lessons, ScreenRules())
    assert result.kept == [] and result.held == {HoldReason.THROWAWAY_SCRIPT: 1}


def test_a_throwaway_script_with_no_fix_shown_is_still_struggle():
    lessons = [lesson(SCRATCH, "s1", fix=None, target_created=True)] * 2
    result = screen(lessons, ScreenRules())
    assert result.held == {HoldReason.NO_FIX_SHOWN: 1} and result.struggle == lessons


def test_a_single_loop_is_kept():
    """Failure guarded against: a loop held for appearing in one session, as a person would not."""
    loop = Signature(Signal.LOOP, ("pytest", "tests/test_x.py"))
    one = lesson(loop, "s1", fix=None)
    result = screen([one], ScreenRules(min_sessions=2))
    assert result.kept == [one] and result.held == {}


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


def test_the_kept_occurrences_decide_whether_the_script_is_throwaway():
    """Failure guarded against: an unfixed non-created sibling hiding a scratch script's lessons."""
    created = [lesson(SCRATCH, s, target_created=True) for s in ("s1", "s2")]
    sibling = lesson(SCRATCH, "s3", fix=None, target_created=False)
    result = screen([*created, sibling], ScreenRules())
    assert result.kept == [] and result.held == {HoldReason.THROWAWAY_SCRIPT: 1}


def test_delivery_filter_drops_inline_failed_command_lessons():
    """Failure guarded against: an older mining's `python -c` lessons reaching a note."""
    inline = lesson(INLINE)
    kept = lesson(MANAGE)
    rules = ScreenRules(min_sessions=1)
    assert taught_since_the_fix_rule([inline, kept], rules) == [kept]


def test_delivery_filter_applies_the_fix_in_min_sessions_rule_to_an_older_store():
    """Failure guarded against: a trap fixed in one session reaching a note or the adapter."""
    one_fix = [lesson(MANAGE, "s1"), lesson(MANAGE, "s2", fix=None)]
    two_fixes = [lesson(TRAP, "s1"), lesson(TRAP, "s2"), lesson(TRAP, "s3", fix=None)]
    assert taught_since_the_fix_rule(one_fix, ScreenRules()) == []
    assert taught_since_the_fix_rule(one_fix, ScreenRules(min_sessions=1)) == [one_fix[0]]
    assert taught_since_the_fix_rule(two_fixes, ScreenRules()) == two_fixes[:2]


def test_delivery_filter_drops_probes_and_scratch_scripts_but_keeps_what_people_said():
    probe = Signature(Signal.FAILED_COMMAND, ("ls", "src", "exit 2 No such file"))
    said = Signature(Signal.CORRECTION, ("use uv",))
    lessons = [lesson(probe, "s1"), lesson(probe, "s2"), lesson(said, "s1")]
    lessons += [lesson(SCRATCH, s, target_created=True) for s in ("s1", "s2")]
    assert taught_since_the_fix_rule(lessons, ScreenRules()) == [lessons[2]]
