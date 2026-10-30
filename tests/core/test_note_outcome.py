"""An action after a note is the fix, something unrelated, or a new error."""

from symbiont.core.note_outcome import Outcome, classify_action

FIXES = ("pip install pyyaml",)


def test_running_the_fix_is_followed_even_if_it_fails():
    assert classify_action(FIXES, "pip install pyyaml && pytest", 0) is Outcome.FOLLOWED
    assert classify_action(FIXES, "pip install pyyaml", 1) is Outcome.FOLLOWED


def test_an_unrelated_action_is_ignored_unless_it_fails():
    assert classify_action(FIXES, "ls", 0) is Outcome.IGNORED
    assert classify_action(FIXES, None, None) is Outcome.IGNORED
    assert classify_action(FIXES, "pytest", 1) is Outcome.BURNED
