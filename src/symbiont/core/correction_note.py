"""A correction told as a story: what was being worked on, the developer's words, what came next.

The developer's own words carry the lesson; a key of eight lowercased words does not. What came
next is the agent's next change, never "fixed": the correction is not a failed command. Pure:
a lesson in, one note of at most NOTE_CHARS out.
"""

import re

from symbiont.core.note_words import MIN_WHILE_CHARS, NOTE_CHARS
from symbiont.miner.credential_patterns import scrub
from symbiont.miner.empty_correction import is_bare_acknowledgment
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
# A turn the harness wrote, or one too short to say what the work was ("yes, option A").
_HARNESS_START = ("<", "[", "http://", "https://")
_MIN_REQUEST_WORDS = 4
# An answer to the agent opens with these, or with a list number; the request, if any, follows.
_REPLY_START = re.compile(
    r"^(?:(?:ok(?:ay)?|yes|yeah|yep|sure|alright|cool|great|perfect|thanks|all good|good"
    r"|\d+(?=\s*[.):-]))\b[\s,.!:)-]*)+",
    re.IGNORECASE,
)
# "i am logged in now" reports the developer's state; it names no work the agent was doing.
_SELF_REPORT = re.compile(r"^(?:i am|i'm|im|i've|i have)\b", re.IGNORECASE)
# Test runners' ticks, box rules and braces: the turn is pasted output, not a request.
_PASTED = re.compile(r"[✓✔✖✗›│{}]|```")
# A request that opens the same as the pushback is the same message said twice.
_SAME_START_CHARS = 30
# A heredoc, or a quote still open at the end of the first line, spans lines: show the first.
_HEREDOC = "<<"


def correction_note(lesson: Lesson) -> str:
    """`While <work>: the developer pushed back: “<words>”. <what came next>`; "" when bare."""
    if is_bare_acknowledgment(lesson.quote):
        return ""
    ending = _what_came_next(lesson)
    said = said_line(lesson.quote, min(SAID_CHARS, NOTE_CHARS - _FRAME - len(ending)))
    if not said:
        return ""
    close = "”" if said.endswith((".", "!", "?", "…")) else "”."
    pushed = f"pushed back: “{said}{close} {ending}"
    return _with_work(_interrupted_work(lesson.asked, said), pushed)


def _what_came_next(lesson: Lesson) -> str:
    """The agent's next change: the files it edited, else the command it ran."""
    edited = edit_clause(resolution_phrase(lesson.resolution))
    if edited:
        return f"Then the agent edited {edited}."
    if lesson.resolution and lesson.fix_commands:
        command = plain_paths(scrub(_one_line(lesson.fix_commands[-1])))
        shown = command if len(command) <= COMMAND_CHARS else command[: COMMAND_CHARS - 1] + "…"
        return f"Then the agent ran `{shown}`."
    phrase = resolution_phrase(lesson.resolution)
    return f"Then the agent {phrase}." if phrase else NOTHING_NEXT


def _one_line(command: str) -> str:
    """A shell command on one line: lines joined by `;`, a heredoc shown by its first line."""
    lines = [line.strip() for line in command.replace("\\\n", " ").splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) > 1 and (_HEREDOC in lines[0] or _opens_a_quote(lines[0])):
        return " ".join(lines[0].split()) + " …"
    return " ".join("; ".join(lines).split())


def _opens_a_quote(line: str) -> bool:
    return line.count("'") % 2 == 1 or line.count('"') % 2 == 1


def _interrupted_work(asked: str, said: str) -> str:
    """The developer's previous request as a clause; "" for harness text, a reply or a repeat."""
    text = plain_paths(REMINDER.sub(" ", asked)).strip()
    if text.startswith(_HARNESS_START) or _PASTED.search(text):
        return ""
    request = _REPLY_START.sub("", text)
    clause = working_on_line("", request, "").rstrip(".!?…")
    if _SELF_REPORT.match(request) or len(clause.split()) < _MIN_REQUEST_WORDS:
        return ""
    return "" if _opening(request) == _opening(said) else clause


def _opening(text: str) -> str:
    return " ".join(_REPLY_START.sub("", text).lower().split())[:_SAME_START_CHARS]


def _with_work(work: str, pushed: str) -> str:
    room = NOTE_CHARS - len(pushed) - len("While : the developer ")
    if not work or room < MIN_WHILE_CHARS:
        return f"The developer {pushed}"
    shown = work if len(work) <= room else work[: room - 1].rstrip() + "…"
    return f"While {shown}: the developer {pushed}"
