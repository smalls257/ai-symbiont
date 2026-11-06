"""The empty-state sentence must promise only what the page offers.

Violation prevented: Paper Tiger. "Restore one" with no Restore control on the page meets the
wording and fails the developer.
"""

from symbiont.miner.screen import HoldReason
from symbiont.service.no_lessons import no_lessons_sentence

HINT = "Restore one from the Ignored list on the left to use it again"


def test_the_restore_hint_appears_only_when_something_is_ignored():
    assert HINT in no_lessons_sentence({}, 2, ignored=2)
    assert HINT not in no_lessons_sentence({HoldReason.NO_FIX_SHOWN: 3}, 2)
    assert "Restore" not in no_lessons_sentence({}, 2)


def test_the_hint_also_follows_other_hold_reasons_when_something_is_ignored():
    said = no_lessons_sentence({HoldReason.NO_FIX_SHOWN: 3}, 2, ignored=1)
    assert said.startswith("No lesson yet") and said.endswith(HINT + ".")
