"""One-sentence verdicts on failure groups, as the developer's session model writes them.

A verdict reaches the dashboard as the group's headline, so a paragraph, a missing lead or a
credential would read as a clean label. Every item is checked and a bad one raises
`VerdictError` naming the field; the service turns that into a resend message. Pure.
"""

from collections.abc import Mapping
from typing import Any

from symbiont.miner.secrets import scrub

# The three leads the mockups show; the lead is the reading the model commits to.
LEADS = ("Worth a look: ", "Fixed in practice: ", "Noise: ")
# One line of a dashboard row; a longer verdict is a summary, not a verdict.
MAX_SENTENCE_CHARS = 220


class VerdictError(ValueError):
    """A verdict that does not have the shape the route takes; the message names the field."""


def verdict_from(item: Mapping[str, Any]) -> tuple[str, str]:
    """A checked (group key, sentence) from a request item; raises VerdictError."""
    key = item.get("key")
    if not isinstance(key, str) or not key:
        raise VerdictError("key must be the group's key from the candidates")
    sentence = item.get("sentence")
    if not isinstance(sentence, str) or not sentence.strip():
        raise VerdictError(f"sentence for {key!r} must be text")
    sentence = scrub(sentence.strip())
    if len(sentence.splitlines()) != 1:
        raise VerdictError(f"sentence for {key!r} must be one line")
    if len(sentence) > MAX_SENTENCE_CHARS:
        raise VerdictError(f"sentence for {key!r} is over {MAX_SENTENCE_CHARS} characters")
    if not sentence.startswith(LEADS):
        raise VerdictError(f"sentence for {key!r} must start with one of: {', '.join(LEADS)}")
    return key, sentence
