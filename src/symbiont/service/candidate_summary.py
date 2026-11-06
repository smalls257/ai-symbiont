"""A summary of a pain point built from rules, for when the session's model has not written one.

A candidate listed with only a title makes the developer open
the transcript to learn what it was about; this states the request, the failure and the ending
in a sentence or two. Plain prose; nothing here calls a model.
"""

from symbiont.core.failure_signature import failure_detail
from symbiont.core.notes import happened
from symbiont.miner.lessons import Lesson
from symbiont.miner.secrets import scrub

SHOWN_CHARS = 160


def rule_summary(lesson: Lesson) -> str:
    """What was asked, what failed and how it ended, scrubbed, in at most three sentences."""
    failure = failure_detail(lesson.quote) or happened(lesson.pain_point.signature)
    parts = []
    if lesson.asked:
        parts.append(f"You asked: {_short(lesson.asked)}")
    parts.append(f"What failed: {_short(failure)}")
    parts.append(outcome_sentence(lesson))
    return scrub(" ".join(parts))


def _short(text: str) -> str:
    """The first line of the text, ended with a full stop and cut to SHOWN_CHARS."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    line = line[: SHOWN_CHARS - 1] + "…" if len(line) > SHOWN_CHARS else line
    return line if line.endswith((".", "!", "?", "…")) else line + "."


def outcome_sentence(lesson: Lesson) -> str:
    """How it ended, in a plain sentence; the one wording the candidate and the summary share."""
    if lesson.resolution:
        return "It was fixed: " + ", then ".join(lesson.resolution) + "."
    if lesson.changed_alongside:
        return "No fix was confirmed; other changes were made before it passed."
    return "The history shows no fix."
