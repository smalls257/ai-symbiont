"""A user turn that holds no instruction is not a correction: "ok", "/compact", markup.

Two rules: `is_empty_correction` blanks a card (under 3 real words); `is_bare_acknowledgment`
decides what never becomes a lesson, and only a slash command, markup or "ok" do.
"""

import re

# The most common openers of SWE-chat corrections that carry no instruction (cipher-box: 275 of
# 1,396 started with "ok") [measured], plus the words that go with them.
ACKNOWLEDGMENTS = frozenset(
    [
        "ok",
        "okay",
        "yes",
        "yeah",
        "yep",
        "sure",
        "thanks",
        "thank",
        "please",
        "go",
        "ahead",
        "continue",
        "proceed",
        "cool",
        "great",
        "nice",
        "perfect",
    ]
)
# Fewer real words than this after the acknowledgments and markup, and nobody was corrected.
MIN_REAL_WORDS = 3
_MARKUP = re.compile(r"<(command-[\w-]+)[^>]*>.*?</\1>|<[^>]+>", re.S)
_SLASH_COMMAND = re.compile(r"(?<!\S)/[\w:-]+(?=\s|$)")
_LEADING_SLASH = re.compile(r"/[\w:-]+(\s|$)")
_WORD = re.compile(r"[A-Za-z']+")


def is_empty_correction(text: str) -> bool:
    """True when `text` holds no instruction: acknowledgments, slash commands and markup only."""
    bare = _SLASH_COMMAND.sub(" ", _MARKUP.sub(" ", text))
    words = [word.lower().strip("'") for word in _WORD.findall(bare)]
    return sum(word not in ACKNOWLEDGMENTS for word in words) < MIN_REAL_WORDS


# A reply that agrees and carries no instruction; "use pnpm" and "wrong file" are not in it, so a
# short real correction stays a lesson.
BARE_ACKNOWLEDGMENTS = frozenset(
    {"ok", "okay", "yes", "yeah", "yep", "sure", "thanks", "thank", "you", "please"}
    | {"continue", "proceed", "go", "on", "ahead", "cool", "great", "nice", "perfect"}
)


def is_bare_acknowledgment(text: str) -> bool:
    """True for a slash command (arguments too), markup only, empty text or only agreement."""
    if _LEADING_SLASH.match(_MARKUP.sub(" ", text).lstrip()):
        return True
    bare = _SLASH_COMMAND.sub(" ", _MARKUP.sub(" ", text))
    words = [word.lower().strip("'") for word in _WORD.findall(bare)]
    return all(word in BARE_ACKNOWLEDGMENTS for word in words)
