"""Pre-registration file format and the frozen check, over an injected git view (no I/O here)."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

HEADER_LINES = 12  # the freeze marker sits in the opening paragraph of every prereg
MAX_AMENDMENT_DEPTH = 8  # a longer chain is a loop or a mistake, never a real history
FROZEN_MARKER = re.compile(r"\bFROZEN (\d{4}-\d{2}-\d{2})")
AMENDS_LINE = re.compile(r"^Amends: (prereg/\S+\.md)\s*$", re.MULTILINE)
DATED_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")


class PreregNotFrozenError(RuntimeError):
    """A scored run was asked for on a prereg that is not committed, unchanged and well formed."""

    def __init__(self, path: str | Path, reason: str) -> None:
        super().__init__(f"prereg {path} is not frozen: {reason}")
        self.path = str(path)
        self.reason = reason


class PathState(StrEnum):
    """Where a prereg file stands against HEAD; only CLEAN is frozen."""

    UNTRACKED = "untracked"
    STAGED = "staged but not committed"
    MODIFIED = "modified in the working tree"
    CLEAN = "clean"


class GitView(Protocol):
    """What the frozen check needs from git; the real adapter is `prereg_git.GitCli`."""

    def root(self) -> Path:
        """The repository root, against which `Amends:` references resolve."""
        ...

    def state(self, path: Path) -> PathState:
        """Whether `path` is untracked, staged, modified or clean against HEAD."""
        ...

    def adding_commit(self, path: Path) -> str:
        """The sha of the commit that added `path`."""
        ...


@dataclass(frozen=True)
class ParsedPrereg:
    """The header fields of a prereg file."""

    title: str
    frozen_on: str
    amends: str | None


@dataclass(frozen=True)
class FrozenPrereg:
    """A prereg that passed the frozen check, with what the results record."""

    path: Path
    commit: str
    sha256: str
    original: Path  # the first file of the amendment chain; this file itself if not an amendment


def parse_prereg(text: str, *, name: str) -> ParsedPrereg:
    """Validate the fields every file in `prereg/` carries: title, freeze date, claim tags."""
    lines = text.splitlines()
    title = lines[0][2:].strip() if lines and lines[0].startswith("# ") else ""
    if not title:
        raise PreregNotFrozenError(name, "the first line must be a '# ' title")
    marker = FROZEN_MARKER.search("\n".join(lines[:HEADER_LINES]))
    if marker is None:
        raise PreregNotFrozenError(
            name, f"no 'FROZEN <date>' marker in the first {HEADER_LINES} lines"
        )
    if "Claim tags:" not in text:
        raise PreregNotFrozenError(name, "no 'Claim tags:' paragraph")
    amends = AMENDS_LINE.search(text)
    if amends and not DATED_NAME.match(Path(name).name):
        raise PreregNotFrozenError(name, "an amendment file name starts with its date, YYYY-MM-DD-")
    return ParsedPrereg(title, marker.group(1), amends.group(1) if amends else None)


def verify_frozen(
    path: Path, git: GitView, read_bytes: Callable[[Path], bytes], *, depth: int = 0
) -> FrozenPrereg:
    """Refuse unless `path` and every file it amends is committed and unchanged."""
    if depth > MAX_AMENDMENT_DEPTH:
        raise PreregNotFrozenError(path, f"amendment chain deeper than {MAX_AMENDMENT_DEPTH}")
    state = git.state(path)
    if state is not PathState.CLEAN:
        raise PreregNotFrozenError(path, state.value)
    raw = read_bytes(path)
    parsed = parse_prereg(raw.decode("utf-8"), name=str(path))
    original = path
    if parsed.amends:
        original = verify_frozen(
            git.root() / parsed.amends, git, read_bytes, depth=depth + 1
        ).original
    return FrozenPrereg(path, git.adding_commit(path), hashlib.sha256(raw).hexdigest(), original)
