"""What reaches the session model is scrubbed again, whatever the store holds.

Failure guarded against: Silent Fallback (trusting stored text, so one old row leaks a token).
"""

from dataclasses import dataclass

from symbiont.service.rule_candidates import offered

SECRET = "abcd1234" + "efgh5678"  # built at runtime so no secret scanner reads a literal


@dataclass(frozen=True)
class Said:
    session_id: str
    step: int
    text: str


def test_a_credential_in_stored_text_never_reaches_the_offer():
    shown, left = offered([Said("a", 1, f"always use token={SECRET}")], {"a": "2026-01-01"})
    assert SECRET not in shown[0]["text"] and left == 0
