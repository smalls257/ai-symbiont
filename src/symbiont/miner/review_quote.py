"""A reviewer's own words kept beside the lesson a model wrote from them.

A model's paraphrase of a ruling narrowed it: a
maintainer said not to `.copy()` in generator code, and the saved lesson said "do not copy
properties in a DuckDB sub-method". The quote is the ruling as the reviewer stated it.
Pure: text in, text out; nothing here reads GitHub.
"""

import re
from enum import StrEnum

# About 300 characters keeps the quote whole inside the 600-character note next to its lead and
# the lesson's own sentence (see core.quoted_rule); it is cut only at a sentence boundary.
MAX_QUOTE_CHARS = 300
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_PULL = re.compile(r"/pull/(\d+)(?:[/?#]|$)")


class ReviewerRole(StrEnum):
    """What the reviewer was to the repository; names of people are never kept."""

    MAINTAINER = "maintainer"
    REVIEWER = "reviewer"


def pull_number(source_url: str) -> int | None:
    """The pull request number in a GitHub pull request address, or None."""
    found = _PULL.search(source_url)
    return int(found.group(1)) if found else None


def capped_at_sentence(text: str) -> str | None:
    """`text` whole if it fits MAX_QUOTE_CHARS, else its longest whole-sentence prefix, else None.

    None means the first sentence alone is over the cap: cutting mid-sentence would change what
    the reviewer said, so the caller must ask for a shorter quote instead.
    """
    if len(text) <= MAX_QUOTE_CHARS:
        return text
    ends = [m.end() for m in _SENTENCE_END.finditer(text[: MAX_QUOTE_CHARS + 1])]
    ends = [end for end in ends if end <= MAX_QUOTE_CHARS]
    return text[: ends[-1]] if ends else None
