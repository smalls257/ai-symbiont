"""A user turn that holds no instruction is not a correction: "ok", "/compact", markup."""

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
_WORD = re.compile(r"[A-Za-z']+")


def is_empty_correction(text: str) -> bool:
    """True when `text` holds no instruction: acknowledgments, slash commands and markup only."""
    bare = _SLASH_COMMAND.sub(" ", _MARKUP.sub(" ", text))
    words = [word.lower().strip("'") for word in _WORD.findall(bare)]
    return sum(word not in ACKNOWLEDGMENTS for word in words) < MIN_REAL_WORDS
