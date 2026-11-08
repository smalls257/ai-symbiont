"""A correction told as a story: what was being worked on, the developer's words, what came next.

The developer's own words carry the lesson; a key of eight lowercased words does not. What came
next is the agent's next change, never "fixed": the correction is not a failed command. Pure:
a lesson in, one note of at most NOTE_CHARS out.
"""

from symbiont.core.note_words import MIN_WHILE_CHARS, NOTE_CHARS
from symbiont.miner.credential_patterns import scrub
from symbiont.miner.empty_correction import is_empty_correction
from symbiont.miner.fix_words import edit_clause, resolution_phrase
from symbiont.miner.incident_words import REMINDER, said_line
from symbiont.miner.lessons import Lesson
from symbiont.miner.shown_paths import plain_paths
from symbiont.miner.story import working_on_line

# The most of the developer's message a note quotes: a sentence or two, not a pasted log.
SAID_CHARS = 160
COMMAND_CHARS = 60
NOTHING_NEXT = "No fix was found in the history."
_FRAME = len("The developer pushed back: “”. ")
# A turn the harness wrote, or one too short to say what the work was.
_HARNESS_START = ("<", "[", "http://", "https://")
_MIN_REQUEST_WORDS = 3


def correction_note(lesson: Lesson) -> str:
    """`While <work>: the developer pushed back: “<words>”. <what came next>`; "" when empty."""
    if is_empty_correction(lesson.quote):
        return ""
    ending = _what_came_next(lesson)
    said = said_line(lesson.quote, min(SAID_CHARS, NOTE_CHARS - _FRAME - len(ending)))
    if not said:
        return ""
    close = "”" if said.endswith((".", "!", "?", "…")) else "”."
    pushed = f"pushed back: “{said}{close} {ending}"
    return _with_work(_interrupted_work(lesson.asked), pushed)


def _what_came_next(lesson: Lesson) -> str:
    """The agent's next change: the files it edited, else the command it ran."""
    edited = edit_clause(resolution_phrase(lesson.resolution))
    if edited:
        return f"Then the agent edited {edited}."
    if lesson.resolution and lesson.fix_commands:
        command = plain_paths(scrub(" ".join(lesson.fix_commands[-1].split())))
        shown = command if len(command) <= COMMAND_CHARS else command[: COMMAND_CHARS - 1] + "…"
        return f"Then the agent ran `{shown}`."
    phrase = resolution_phrase(lesson.resolution)
    return f"Then the agent {phrase}." if phrase else NOTHING_NEXT


def _interrupted_work(asked: str) -> str:
    """The developer's previous request as a clause; "" for harness text or a bare reply."""
    text = REMINDER.sub(" ", asked).strip()
    if text.startswith(_HARNESS_START) or len(text.split()) < _MIN_REQUEST_WORDS:
        return ""
    return working_on_line("", text, "").rstrip(".!?…")


def _with_work(work: str, pushed: str) -> str:
    room = NOTE_CHARS - len(pushed) - len("While : the developer ")
    if not work or room < MIN_WHILE_CHARS:
        return f"The developer {pushed}"
    shown = work if len(work) <= room else work[: room - 1].rstrip() + "…"
    return f"While {shown}: the developer {pushed}"
