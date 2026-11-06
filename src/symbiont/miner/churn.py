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
from symbiont.miner.codebase import repo_relative
from symbiont.miner.commands import program_words
from symbiont.records.schema import Kind, Record

# Both readers write a file creation as a diff against /dev/null.
CREATES = "--- /dev/null"


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


def _session_churn(session: Sequence[Record], repo_names: frozenset[str]) -> list[FileChurn]:
    """The churn of one session, minus scratch files: created here and removed again."""
    scratch = _scratch_files(session, repo_names)
    counts: Counter[tuple[str, str]] = Counter()
    for record in session:
        if not applied_edit(record) or not record.files:
            continue
        path = repo_relative(record.files[0], repo_names)
        if path is not None and path not in scratch:
            counts[(record.session_id, path)] += 1
    return [FileChurn(path, sid, edits) for (sid, path), edits in sorted(counts.items())]


def _scratch_files(session: Sequence[Record], repo_names: frozenset[str]) -> set[str]:
    """Repo-relative files this session created and a later `rm` removed."""
    created: set[str] = set()
    scratch: set[str] = set()
    for record in session:
        if applied_edit(record) and record.files and (record.diff or "").startswith(CREATES):
            path = repo_relative(record.files[0], repo_names)
            if path is not None:
                created.add(path)
        for gone in _removed_by(record, repo_names):
            if gone in created:
                scratch.add(gone)
    return scratch


def _removed_by(record: Record, repo_names: frozenset[str]) -> list[str]:
    """Repo-relative files a successful `rm` command removed."""
    if record.kind != Kind.COMMAND or record.exit_code != 0:
        return []
    program, args = program_words(record.command or "")
    if program != "rm":
        return []
    named = (repo_relative(arg, repo_names) for arg in args if not arg.startswith("-"))
    return [path for path in named if path is not None]
