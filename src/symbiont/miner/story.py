"""A failure told so a new teammate can follow it: working on, what broke, how it ended.

The short fix phrase says which file; a reader also needs the command that failed, the one error
line that says why, and the one line that changed. Pure: a lesson and the session's goal in, three
bounded plain lines out. Each line is "" when the history cannot say it, never a placeholder.
"""

import re
from dataclasses import dataclass

from symbiont.miner.credential_patterns import scrub
from symbiont.miner.failure_keys import broke_in_words
from symbiont.miner.fix_words import Step, edit_clause, last_command, resolution_phrase
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.miner.shown_paths import plain_paths
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
# A relative path of three or more parts shortens to its file name; `.git/index.lock` stays.
_DEEP_PATH = re.compile(r"(?<![\w:/.-])(?:[\w.@-]+/){2,}([\w.@-]+)")
_LEVEL = re.compile(r"^(?:fatal|error|warning):\s*", re.IGNORECASE)
_POOLED = re.compile(r", and \d+ other fix(?:es)?$")
_RAN_AGAIN = re.compile(r"re-ran ([^,]+)")


@dataclass(frozen=True)
class Story:
    """Three lines: what was being worked on, what broke and how it ended; each may be empty."""

    working_on: str
    broke: str
    ended: str


def story_of(
    lesson: Lesson,
    goal: str = "",
    repo_names: frozenset[str] = frozenset(),
    setup: str | None = None,
) -> Story:
    """The story of a failed-command lesson.

    `goal` is the session model's own words, if any; `repo_names` shortens absolute paths to
    repo-relative ones; `setup` is the command the miner identified as the setup step, if any.
    """
    return Story(
        working_on_line(goal, lesson.asked, lesson.agent_intent),
        broke_line(lesson, repo_names),
        ended_line(lesson, repo_names, setup),
    )


def working_on_line(goal: str, asked: str, intent: str) -> str:
    """The goal, else the first sentence of the request, else the agent's stated intent."""
    for text in (goal, asked, intent):
        flat = " ".join(text.split())
        if flat:
            return _cut(scrub(_SENTENCE_END.split(flat)[0]), WORKING_ON_CHARS)
    return ""


def broke_line(lesson: Lesson, repo_names: frozenset[str] = frozenset()) -> str:
    """The command and the most specific error line; "failed (exit N)" when there is no message."""
    if lesson.pain_point.signature.signal is not Signal.FAILED_COMMAND:
        return ""
    command = _command_of(lesson, repo_names)
    error = _error_of(lesson)
    if not error:
        return f"`{command}` failed{_without_message(lesson.pain_point.signature.key[-1])}"
    verb = "failed to compile — " if _TYPESCRIPT.match(error) else "failed: "
    return _cut(f"`{command}` {verb}{_say(error, repo_names)}", BROKE_CHARS)


def error_summary(lesson: Lesson, repo_names: frozenset[str] = frozenset()) -> str:
    """The one clean error line of a failure for a suggestion chip; "" when output said none."""
    error = _error_of(lesson)
    return _say(error, repo_names) if error else ""


def _error_of(lesson: Lesson) -> str:
    """The most specific line of the failure's own output (the command's lines are not output)."""
    return specific_error_line([*lesson.error_lines, *_output_lines(lesson)])


def _output_lines(lesson: Lesson) -> list[str]:
    """The quote without its `$ command` head, which may span several lines."""
    head = f"$ {lesson.failed_command}\n"
    if lesson.failed_command and lesson.quote.startswith(head):
        return lesson.quote[len(head) :].splitlines()
    return lesson.quote.splitlines()[1:]


def _without_message(reason: str) -> str:
    """` (exit 1)` or ` with <plain error name>` for a failure whose output said nothing useful."""
    if reason.startswith("exit "):
        return f" ({reason})"
    return f" with {broke_in_words(reason)}" if reason and reason != "-" else ""


def specific_error_line(lines: list[str]) -> str:
    """The line that says why: a location and a code beat a message; else the last real line."""
    cleaned = [_clean(line) for line in lines]
    useful = [line for line in cleaned if line and not _BOILERPLATE.search(line)]
    ranked = sorted(enumerate(useful), key=lambda item: (-_score(item[1]), item[0]))
    if ranked and _score(ranked[0][1]) > 0:
        return ranked[0][1]
    return useful[-1] if useful else ""


def ended_line(
    lesson: Lesson, repo_names: frozenset[str] = frozenset(), setup: str | None = None
) -> str:
    """How it ended in one line; the plain reason when no fix was shown."""
    phrase = resolution_phrase(lesson.resolution)
    if not phrase:
        return _unresolved(lesson)
    names = edit_clause(phrase)
    if names:
        edited = _edited(names, lesson, repo_names) + _passed(phrase, lesson, repo_names)
        return _cut(edited + _more(phrase), ENDED_CHARS)
    return _cut(_by_command(lesson, phrase, repo_names, setup) + _more(phrase), ENDED_CHARS)


def _unresolved(lesson: Lesson) -> str:
    if lesson.pain_point.signature.signal is not Signal.FAILED_COMMAND:
        return ""
    reason = lesson.unresolved_because
    return "no fix was shown" + (f": {reason}" if reason else "")


def _edited(names: str, lesson: Lesson, repo_names: frozenset[str]) -> str:
    line = plain_paths(scrub(lesson.fix_added), repo_names)
    return f"fixed by editing {names}" + (f" (added `{line}`)" if line else "")


def _more(phrase: str) -> str:
    """The ", and N other fixes" a pooled resolution ends with; "" for a single fix."""
    found = _POOLED.search(phrase)
    return found.group(0) if found else ""


def _passed(phrase: str, lesson: Lesson, repo_names: frozenset[str]) -> str:
    if not _RAN_AGAIN.search(phrase):
        return ""
    return f", then `{_command_of(lesson, repo_names)}` passed"


def _by_command(lesson: Lesson, phrase: str, repo_names: frozenset[str], setup: str | None) -> str:
    """The command that made the difference: the setup step when the miner found one."""
    failed = lesson.pain_point.signature.key[0]
    chosen = setup or last_command([Step(command=c) for c in lesson.fix_commands], failed)
    if not chosen:
        return phrase
    command = working_command(chosen, repo_names)
    if setup:
        return f"fixed the setup: ran `{command}`, then it passed"
    if lesson.fix is not None and lesson.fix.value == "corrected_command":
        return f"ran it correctly: `{command}`"
    return f"fixed by running `{command}`, then `{_command_of(lesson, repo_names)}` passed"


def _command_of(lesson: Lesson, repo_names: frozenset[str]) -> str:
    typed = lesson.failed_command or (lesson.quote.splitlines()[0] if lesson.quote else "")
    return _cut(working_command(typed.removeprefix("$ "), repo_names), COMMAND_CHARS)


def _clean(line: str) -> str:
    return " ".join(_ANSI.sub("", line).split())


def _score(line: str) -> int:
    return (
        3 * bool(_LOCATION.search(line))
        + 2 * bool(_CODE.search(line))
        + 2 * bool(_MESSAGE.search(line))
        + bool(_LEVEL.match(line))
    )


def _say(line: str, repo_names: frozenset[str] = frozenset()) -> str:
    """The error line as a teammate reads it: short paths, no `fatal:` prefix, the code last."""
    text = _clean(line)
    found = _TYPESCRIPT.match(text)
    if found:
        base = plain_paths(found["path"].replace("\\", "/"), repo_names).rsplit("/", 1)[-1]
        message = found["message"].rstrip(". ")
        return _cut(scrub(f"`{base}:{found['line']}`: {message} ({found['code']})"), ERROR_CHARS)
    shown = _DEEP_PATH.sub(r"\1", plain_paths(scrub(_LEVEL.sub("", text)), repo_names))
    return _cut(shown, ERROR_CHARS)


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,(") + _CUT
