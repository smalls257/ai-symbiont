"""Churn: how many edits each file took in each session.

Rework used to be mined as a lesson, but 74% of rework groups sat in one session and the top
files were "the file the task edits" (a note that says "be careful with the file you were asked
to change" teaches nothing). Churn is a measure, not a lesson: counted and shown, never taught.
Only repo-relative paths count; scratch files the agent made and removed are not the codebase.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.miner.changes import applied_edit
from symbiont.miner.commands import program_words
from symbiont.records.schema import Kind, Record

_THROWAWAY_DIRS = ("/tmp/", "/var/folders/", "/private/tmp/")


@dataclass(frozen=True)
class FileChurn:
    """Applied edits to one repo-relative file in one session."""

    file: str
    session_id: str
    edits: int


def churn(sessions: Sequence[Sequence[Record]], repo_names: frozenset[str]) -> list[FileChurn]:
    """Edits per file per session; `repo_names` are the directory names the repo goes by.

    A path is repo-relative when it is already relative, or absolute with a repo name among its
    directories (what follows the name). Anything else is outside the repo and is skipped.
    """
    return [row for session in sessions for row in _session_churn(session, repo_names)]


def repo_relative(path: str, repo_names: frozenset[str]) -> str | None:
    """`path` relative to the repo root, or None when it lies outside the repo."""
    if path.startswith(_THROWAWAY_DIRS):
        return None
    if not path.startswith("/"):
        relative = path.removeprefix("./")
        return None if relative.startswith("..") or not relative else relative
    parts = path.split("/")
    # The outermost match: a repo `sqlglot` holds a package `sqlglot`.
    inside = [i for i, part in enumerate(parts[:-1]) if part in repo_names]
    return "/".join(parts[inside[0] + 1 :]) if inside else None


def _session_churn(session: Sequence[Record], repo_names: frozenset[str]) -> list[FileChurn]:
    """The churn of one session, minus files the agent removed again."""
    removed = _removed_paths(session)
    counts: Counter[tuple[str, str]] = Counter()
    for record in session:
        if not applied_edit(record) or not record.files:
            continue
        path = repo_relative(record.files[0], repo_names)
        if path is not None and not _was_removed(path, removed):
            counts[(record.session_id, path)] += 1
    return [FileChurn(path, sid, edits) for (sid, path), edits in sorted(counts.items())]


def _removed_paths(session: Sequence[Record]) -> set[str]:
    """Arguments of `rm` commands in the session: the files the agent cleaned up."""
    removed: set[str] = set()
    for record in session:
        if record.kind != Kind.COMMAND or record.exit_code != 0:
            continue
        program, args = program_words(record.command or "")
        if program == "rm":
            removed.update(arg.removeprefix("./") for arg in args if not arg.startswith("-"))
    return removed


def _was_removed(path: str, removed: set[str]) -> bool:
    """True when an `rm` named the file, relative to the repo or by an absolute path."""
    return any(path == gone or gone.endswith("/" + path) for gone in removed)
