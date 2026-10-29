"""Lessons for the lesson-capacity probe (LCAP): one failed command and the command that fixed it.

A lesson is kept only when every key detail a scorer checks (command, file, error class, the fix's
added tokens) is present and short; a pair the records cannot fill is dropped and counted by
reason, never filled with a guess. Pure: records in, lessons out. A lesson reads as domain prose.
"""

import hashlib
import re
import shlex
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.miner.commands import normalise_command
from symbiont.records.schema import Kind, Record

ERROR_CLASS = re.compile(r"\b([A-Z]\w*(?:Error|Exception))\b")
# The raised error itself, `NameError: message` or a bare `NameError` ending the line, not code
# that merely names a class (`except (ValueError, TypeError):`).
_RAISED = re.compile(r"\b([A-Z]\w*(?:Error|Exception))(?::\s|$)")
# AssertionError is a failing test, not a mistake in how the command was run.
_NOT_A_RUN_MISTAKE = frozenset({"AssertionError"})
_CD_PREFIX = re.compile(r"^\s*cd\s+\S+\s*&&\s*")
_WORKSPACE = re.compile(r"/workspace/[\w.-]+")
# Output-shape flags change what is printed, not whether the run works: a fix made only of
# them teaches nothing about the failure.
_COSMETIC = frozenset(
    {"-v", "-vv", "-q", "-s", "-x", "-xvs", "-xv", "--tb=short", "--tb=no", "--tb=line"}
    | {"2>&1", "|", "head", "tail", "-n", "-5", "-10", "-20", "-30", "-50"}
)
MAX_COMMAND_CHARS = 120  # longer commands are inline scripts, not a recallable command
MAX_ERROR_CHARS = 100
MAX_ADDED_TOKENS = 4  # a fix that rewrites the whole command is a different command
MAX_LESSONS_PER_REPO = 2  # spread lessons across repos so one repo cannot dominate a set


@dataclass(frozen=True)
class Lesson:
    """One mined pain point with its correction, in the fields the scorer checks."""

    lesson_id: str
    repo: str
    program: str
    file: str
    failed: str
    error: str
    error_class: str
    fix: str
    added: tuple[str, ...]

    def text(self) -> str:
        """The lesson as one line of domain prose."""
        return (
            f"In {self.repo}, `{self.failed}` failed with {self.error}; run `{self.fix}` instead."
        )


def repo_name(project: str) -> str:
    """`Unidata__MetPy` as `Unidata/MetPy`."""
    return project.replace("__", "/", 1)


def lessons_in_session(session: Sequence[Record], drops: Counter[str]) -> list[Lesson]:
    """Every failed command in `session` that a later, different command fixed."""
    commands = [r for r in session if r.kind == Kind.COMMAND and r.exit_code is not None]
    found = []
    for position, failed in enumerate(commands):
        if failed.exit_code == 0:
            continue
        lesson = _lesson_for(failed, commands[position + 1 :], drops)
        if lesson is not None:
            found.append(lesson)
    return found


def _lesson_for(failed: Record, later: Sequence[Record], drops: Counter[str]) -> Lesson | None:
    fix = _first_fix(failed, later)
    if fix is None:
        drops["no later success on the same program and target"] += 1
        return None
    reason = _unusable(failed, fix)
    if reason:
        drops[reason] += 1
        return None
    return _build(failed, fix)


def _first_fix(failed: Record, later: Sequence[Record]) -> Record | None:
    wanted = normalise_command(failed.command or "")
    for record in later:
        if record.exit_code == 0 and normalise_command(record.command or "") == wanted:
            return record
    return None


def _unusable(failed: Record, fix: Record) -> str | None:
    before, after = shown_command(failed.command or ""), shown_command(fix.command or "")
    if "\n" in before + after or max(len(before), len(after)) > MAX_COMMAND_CHARS:
        return "command too long or multi-line"
    error = error_line(failed.raw)
    if error is None:
        return "no named error, or only an AssertionError"
    added = added_tokens(before, after)
    if not added or len(added) > MAX_ADDED_TOKENS:
        return "fix adds no token or rewrites the command"
    if not key_tokens(added):
        return "fix only changes output flags"
    return None


def _error_class(error: str) -> str:
    """The exception class named in the error line; a line without one raises ValueError."""
    found = ERROR_CLASS.search(error)
    if found is None:
        raise ValueError(f"no error class in {error!r}")
    return found.group(1)


def _build(failed: Record, fix: Record) -> Lesson:
    before, after = shown_command(failed.command or ""), shown_command(fix.command or "")
    error = error_line(failed.raw) or ""
    program, target = normalise_command(before)
    lesson_id = hashlib.sha1(f"{failed.session_id}:{failed.step}".encode()).hexdigest()[:12]
    return Lesson(
        lesson_id=lesson_id,
        repo=repo_name(failed.project),
        program=program,
        file=target,
        failed=before,
        error=error,
        error_class=_error_class(error),
        fix=after,
        added=key_tokens(added_tokens(before, after)),
    )


def _error_class(error: str) -> str:
    match = ERROR_CLASS.search(error)
    if match is None:
        raise ValueError("a lesson's error line must name an error class")
    return match.group(1)


def shown_command(command: str) -> str:
    """The command as a lesson shows it: no leading `cd`, workspace paths as `.`."""
    return _WORKSPACE.sub(".", _CD_PREFIX.sub("", command)).strip()


def error_line(output: str) -> str | None:
    """`ErrorClass: message` from the last line naming an error class, clipped; None if none."""
    for line in reversed(output.splitlines()):
        match = _RAISED.search(line.rstrip())
        if match and match.group(1) not in _NOT_A_RUN_MISTAKE:
            text = _WORKSPACE.sub(".", line.rstrip()[match.start() :]).strip()
            return text[:MAX_ERROR_CHARS]
        if match:
            return None
    return None


def added_tokens(before: str, after: str) -> tuple[str, ...]:
    """Shell words of `after` that `before` lacks, in order: the change the fix made."""
    had = Counter(_words(before))
    added = []
    for word in _words(after):
        if had[word] > 0:
            had[word] -= 1
        else:
            added.append(word)
    return tuple(added)


def key_tokens(added: tuple[str, ...]) -> tuple[str, ...]:
    """The added words a recall must name: output-shape flags are not part of the fix."""
    return tuple(token for token in added if token not in _COSMETIC)


def _words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def select_lessons(candidates: Sequence[Lesson], count: int) -> list[Lesson]:
    """`count` lessons in a fixed order, one per distinct failure, at most two per repo.

    Order is by lesson id (a hash), so the first 10 of the 100 are the 10-lesson set: sets nest.
    Raises ValueError when the pool holds fewer usable lessons than asked.
    """
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    per_repo: Counter[str] = Counter()
    chosen = []
    for lesson in sorted(candidates, key=lambda item: item.lesson_id):
        key = (lesson.repo, lesson.error_class, lesson.added)
        if key in seen or per_repo[lesson.repo] >= MAX_LESSONS_PER_REPO:
            continue
        seen.add(key)
        per_repo[lesson.repo] += 1
        chosen.append(lesson)
    if len(chosen) < count:
        raise ValueError(f"pool holds {len(chosen)} usable lessons, {count} asked")
    return chosen[:count]
