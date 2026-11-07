"""A failure told so a new teammate can follow it: working on, what broke, how it ended.

The short fix phrase says which file; a reader also needs the command that failed, the one error
line that says why, and the one line that changed. Pure: a lesson and the session's goal in, three
bounded plain lines out. Each line is "" when the history cannot say it, never a placeholder.
"""

import re
from dataclasses import dataclass

from symbiont.miner.credential_patterns import scrub
from symbiont.miner.failure_keys import broke_in_words
from symbiont.miner.fix_words import edit_clause, resolution_phrase
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.miner.working_command import working_command

WORKING_ON_CHARS = 120
COMMAND_CHARS = 60
ERROR_CHARS = 130
BROKE_CHARS = 200
ENDED_CHARS = 200
_CUT = "…"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")
# Runner noise that says a command failed without saying why.
_BOILERPLATE = re.compile(
    r"ELIFECYCLE|ERR_PNPM_|Exit status|Command failed with exit code|^npm ERR!|\bUnable to compile"
    r"|^\$ |^\d+ (?:failed|passed|error)|^\s*$|^\s*at\s|^Process exited",
    re.IGNORECASE,
)
_LOCATION = re.compile(r"[\w./\\-]+\.\w+[:(]\d+")
_CODE = re.compile(r"\b(?:TS|E|ERR|TS\d)\d{3,5}\b|\berror TS\d+")
_MESSAGE = re.compile(r"\w*(?:Error|Exception):? \S|\berror:? \S")
_TYPESCRIPT = re.compile(
    r"^(?P<path>[\w./\\@-]+)[(:](?P<line>\d+)(?:[,:]\d+)?\)?:?\s*(?:error\s+)?"
    r"(?P<code>TS\d+):\s*(?P<message>.*)$"
)
_PATH = re.compile(r"(?:[\w.@-]+/)+([\w.@-]+)")
_POOLED = re.compile(r", and \d+ other fix(?:es)?$")
_RAN_AGAIN = re.compile(r"re-ran ([^,]+)")


@dataclass(frozen=True)
class Story:
    """Three lines: what was being worked on, what broke and how it ended; each may be empty."""

    working_on: str
    broke: str
    ended: str


def story_of(lesson: Lesson, goal: str = "") -> Story:
    """The story of a failed-command lesson; `goal` is the session model's own words, if any."""
    return Story(
        working_on_line(goal, lesson.asked, lesson.agent_intent),
        broke_line(lesson),
        ended_line(lesson),
    )


def working_on_line(goal: str, asked: str, intent: str) -> str:
    """The goal, else the first sentence of the request, else the agent's stated intent."""
    for text in (goal, asked, intent):
        flat = " ".join(text.split())
        if flat:
            return _cut(scrub(_SENTENCE_END.split(flat)[0]), WORKING_ON_CHARS)
    return ""


def broke_line(lesson: Lesson) -> str:
    """The command and the most specific error line; "failed (exit N)" when there is no message."""
    if lesson.pain_point.signature.signal is not Signal.FAILED_COMMAND:
        return ""
    command = _command_of(lesson)
    error = specific_error_line([*lesson.error_lines, *lesson.quote.splitlines()[1:]])
    if not error:
        return f"`{command}` failed{_without_message(lesson.pain_point.signature.key[-1])}"
    verb = "failed to compile — " if _TYPESCRIPT.match(_clean(error)) else "failed: "
    return _cut(f"`{command}` {verb}{_say(error)}", BROKE_CHARS)


def _without_message(reason: str) -> str:
    """` (exit 1)` or ` with <plain error name>` for a failure whose output said nothing useful."""
    if reason.startswith("exit "):
        return f" ({reason})"
    return f" with {broke_in_words(reason)}" if reason and reason != "-" else ""


def specific_error_line(lines: list[str]) -> str:
    """The line that says why: a location and a code beat a message beat the rest; "" for none."""
    cleaned = [_clean(line) for line in lines]
    useful = [line for line in cleaned if line and not _BOILERPLATE.search(line)]
    ranked = sorted(enumerate(useful), key=lambda item: (-_score(item[1]), item[0]))
    return ranked[0][1] if ranked and _score(ranked[0][1]) > 0 else ""


def ended_line(lesson: Lesson) -> str:
    """How it ended in one line; the plain reason when no fix was shown."""
    phrase = resolution_phrase(lesson.resolution)
    if not phrase:
        return _unresolved(lesson)
    names = edit_clause(phrase)
    if names:
        return _cut(_edited(names, lesson) + _passed(phrase, lesson) + _more(phrase), ENDED_CHARS)
    return _cut(_by_command(lesson, phrase) + _more(phrase), ENDED_CHARS)


def _unresolved(lesson: Lesson) -> str:
    if lesson.pain_point.signature.signal is not Signal.FAILED_COMMAND:
        return ""
    reason = lesson.unresolved_because
    return "no fix was shown" + (f": {reason}" if reason else "")


def _edited(names: str, lesson: Lesson) -> str:
    added = f" (added `{scrub(lesson.fix_added)}`)" if lesson.fix_added else ""
    return f"fixed by editing {names}{added}"


def _more(phrase: str) -> str:
    """The ", and N other fixes" a pooled resolution ends with; "" for a single fix."""
    found = _POOLED.search(phrase)
    return found.group(0) if found else ""


def _passed(phrase: str, lesson: Lesson) -> str:
    if not _RAN_AGAIN.search(phrase):
        return ""
    return f", then `{_command_of(lesson)}` passed"


def _by_command(lesson: Lesson, phrase: str) -> str:
    if not lesson.fix_commands:
        return phrase
    command = working_command(lesson.fix_commands[-1])
    if lesson.fix is not None and lesson.fix.value == "corrected_command":
        return f"ran it correctly: `{command}`"
    return f"fixed the setup: ran `{command}`, then it passed"


def _command_of(lesson: Lesson) -> str:
    first = lesson.quote.splitlines()[0] if lesson.quote else ""
    return _cut(working_command(first.removeprefix("$ ")), COMMAND_CHARS)


def _clean(line: str) -> str:
    return " ".join(_ANSI.sub("", line).split())


def _score(line: str) -> int:
    return (
        3 * bool(_LOCATION.search(line))
        + 2 * bool(_CODE.search(line))
        + 2 * bool(_MESSAGE.search(line))
    )


def _say(line: str) -> str:
    """The error line as a teammate reads it: base name and line number, the code last."""
    text = _clean(line)
    found = _TYPESCRIPT.match(text)
    if found:
        base = found["path"].replace("\\", "/").rsplit("/", 1)[-1]
        message = found["message"].rstrip(". ")
        return _cut(scrub(f"`{base}:{found['line']}`: {message} ({found['code']})"), ERROR_CHARS)
    return _cut(scrub(_PATH.sub(r"\1", text)), ERROR_CHARS)


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,(") + _CUT
