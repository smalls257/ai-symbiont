"""Plug round 4's Spark text, pure: prompts that send a lesson's template text, and reply checks.

A rewrite must start "Applies when", fit one line and copy the failed command and the fix verbatim
in backticks, else RewriteRejectedError. Invented situations must be a JSON array of short strings;
an entry that quotes the fix is dropped and counted, because a situation naming the answer teaches
nothing.
"""

import json
from dataclasses import dataclass

from lessons import Lesson

MAX_REWRITE_CHARS = 400
MAX_SITUATION_CHARS = 300
REWRITE_START = "Applies when"


class RewriteRejectedError(ValueError):
    """A rewrite that changes the commands, spans lines or misses the trigger form."""


class SituationsRejectedError(ValueError):
    """A reply that is not a JSON array of strings."""


@dataclass(frozen=True)
class Invented:
    """The situations kept for one lesson and how many were dropped for quoting the fix."""

    situations: tuple[str, ...]
    dropped: int


def rewrite_prompt(lesson: Lesson) -> str:
    """Ask for the lesson as one trigger sentence with the same two commands."""
    return (
        "Rewrite this lesson for a coding agent as ONE sentence of exactly this form:\n"
        f"{REWRITE_START} <the condition under which it applies, in plain words>: run "
        f"`{lesson.fix}` instead of `{lesson.failed}`.\n"
        "Copy both commands exactly, inside backticks. Add no other advice.\n\n"
        f"Lesson: {lesson.text()}"
    )


def checked_rewrite(lesson: Lesson, reply: str) -> str:
    """The rewrite if it keeps both commands verbatim and the trigger form; else raises."""
    text = reply.strip()
    if "\n" in text or len(text) > MAX_REWRITE_CHARS:
        raise RewriteRejectedError("not one short line")
    if not text.startswith(REWRITE_START):
        raise RewriteRejectedError(f"does not start with {REWRITE_START!r}")
    if f"`{lesson.fix}`" not in text or f"`{lesson.failed}`" not in text:
        raise RewriteRejectedError("a command was not copied verbatim")
    return text


def invent_prompt(lesson: Lesson, count: int) -> str:
    """Ask for `count` varied moments where the lesson applies, without its fix."""
    return (
        f"Here is a lesson a coding agent learned:\n{lesson.text()}\n\n"
        f"Write {count} different short descriptions of a moment in a coding session where this "
        "lesson applies: the command just run, the file being worked on and the error seen. "
        "Vary the wording, file names and error details plausibly but keep the same failure. "
        "Do not mention the fix. Reply with only a JSON array of strings."
    )


def parsed_situations(lesson: Lesson, reply: str) -> Invented:
    """The usable situations of a reply; raises SituationsRejectedError if it is not an array."""
    start, end = reply.find("["), reply.rfind("]")
    if start < 0 or end <= start:
        raise SituationsRejectedError("no JSON array in the reply")
    try:
        found = json.loads(reply[start : end + 1])
    except json.JSONDecodeError as error:
        raise SituationsRejectedError(f"not JSON: {error.msg}") from error
    if not isinstance(found, list) or not all(isinstance(entry, str) for entry in found):
        raise SituationsRejectedError("not a JSON array of strings")
    short = [entry.strip() for entry in found if 0 < len(entry.strip()) <= MAX_SITUATION_CHARS]
    kept = tuple(entry for entry in short if not quotes_fix(lesson, entry))
    return Invented(kept, len(found) - len(kept))


def quotes_fix(lesson: Lesson, situation: str) -> bool:
    """True if the situation contains the fix command or every token the fix added."""
    if lesson.fix in situation:
        return True
    return bool(lesson.added) and all(token in situation for token in lesson.added)
