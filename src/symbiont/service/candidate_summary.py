"""A summary of a pain point built from rules, for when the session's model has not written one.

A candidate listed with only a title makes the developer open the transcript to learn what it was
about; this joins the three story lines (`miner.story`) for a plain-text consumer. Nothing here
calls a model.
"""

from symbiont.miner.fix_words import resolution_phrase
from symbiont.miner.lessons import Lesson
from symbiont.miner.secrets import scrub
from symbiont.miner.story import story_of


def rule_summary(lesson: Lesson, goal: str = "") -> str:
    """The story lines as labeled plain text, one per line, for a consumer with no layout."""
    story = story_of(lesson, goal)
    labeled = (
        ("Working on", story.working_on),
        ("What broke", story.broke),
        ("How it ended", story.ended),
    )
    return scrub("\n".join(f"{label}: {line}" for label, line in labeled if line))


def outcome_sentence(lesson: Lesson) -> str:
    """How it ended, in a plain sentence; the one wording the candidate and the summary share."""
    if lesson.resolution:
        return f"It was fixed: {resolution_phrase(lesson.resolution)}."
    if lesson.changed_alongside:
        return "No fix was confirmed; other changes were made before it passed."
    return "The history shows no fix."
