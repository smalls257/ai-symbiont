"""A summary of a pain point built from rules, for when the session's model has not written one.

A candidate listed with only a title makes the developer open the transcript to learn what it was
about; this states the failure and the ending in two short sentences. Plain prose, no quoted
request (the session page shows it), no code, no path beyond a file name; nothing here calls a
model.
"""

from symbiont.core.notes import happened
from symbiont.miner.failure_keys import broke_in_words
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.miner.secrets import scrub

# Two sentences a developer reads at a glance in the Inbox (owner: "word vomit").
SUMMARY_CHARS = 200
FAILURE_CHARS = 100
_CUT = "…"


def rule_summary(lesson: Lesson) -> str:
    """What failed and how it ended, scrubbed, in at most two sentences of SUMMARY_CHARS."""
    text = f"{_sentence(_failure_words(lesson))} {outcome_sentence(lesson)}"
    return _capped(scrub(text), SUMMARY_CHARS)


def _failure_words(lesson: Lesson) -> str:
    """What failed in plain words: the program and what broke, never the raw error output."""
    signature = lesson.pain_point.signature
    if signature.signal is Signal.FAILED_COMMAND:
        program, _, broke = signature.key
        return f"{program} failed with {broke_in_words(broke)}"
    return happened(signature)


def _sentence(text: str) -> str:
    """The first line of the text, cut to FAILURE_CHARS and ended with a full stop."""
    line = " ".join(text.split())
    line = _capped(line, FAILURE_CHARS)
    return line if line.endswith((".", "!", "?", _CUT)) else line + "."


def _capped(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + _CUT


def outcome_sentence(lesson: Lesson) -> str:
    """How it ended, in a plain sentence; the one wording the candidate and the summary share."""
    if lesson.resolution:
        return "It was fixed: " + ", then ".join(lesson.resolution) + "."
    if lesson.changed_alongside:
        return "No fix was confirmed; other changes were made before it passed."
    return "The history shows no fix."
