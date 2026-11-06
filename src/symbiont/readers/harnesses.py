"""The harness registry: which harnesses exist, how to spot one and where its logs live.

Files used to branch on "claude_code" and "muse_code" one by one, so a new harness meant eleven
edits. Now it is one reader module, one `Harness` entry here and one `HookProfile` entry in
`symbiont.delivery.hook_profiles`; every other file asks this registry. An unknown id raises, so
nothing quietly falls back to Claude Code.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from symbiont.readers import claude_code, muse_code


class StopCadence(StrEnum):
    """How often a harness fires its Stop hook, which decides when reflection can be asked."""

    END_OF_SESSION = "end_of_session"
    EVERY_TURN = "every_turn"


class UnknownHarnessError(ValueError):
    """A harness id nothing registered; the message names it and the known ids."""


@dataclass(frozen=True)
class Harness:
    """One coding harness, as the rest of symbiont needs to know it."""

    id: str  # stored in records and settings files, never renamed
    label: str  # what a developer reads: "Claude Code"
    reader: str  # key into readers.READERS
    env_markers: tuple[str, ...]  # environment variables the harness sets for its hooks
    stop_cadence: StopCadence
    find_sessions: Callable[[Path, Mapping[str, str], Path], list[Path]]  # repo_dir, environ, home
    sessions_live_in: Callable[[Mapping[str, str], Path], Path]  # for the "looked in" message
    plugin_setup: tuple[tuple[str, ...], ...]  # CLI commands that register the plugin


def _claude_sessions(repo_dir: Path, environ: Mapping[str, str], home: Path) -> list[Path]:
    return claude_code.session_logs(repo_dir, home)


def _claude_sessions_live_in(environ: Mapping[str, str], home: Path) -> Path:
    return home / ".claude" / "projects"


def _muse_sessions(repo_dir: Path, environ: Mapping[str, str], home: Path) -> list[Path]:
    return muse_code.session_logs(repo_dir, muse_code.muse_store_root(environ, home))


def _muse_sessions_live_in(environ: Mapping[str, str], home: Path) -> Path:
    return muse_code.muse_store_root(environ, home) / "muse" / "sessions"


PLUGIN_SOURCE = "https://github.com/smalls257/ai-symbiont"  # where both marketplaces install from

# Muse Code first: it also sets CLAUDE_PLUGIN_ROOT, so Claude Code's markers would claim it.
# MUSE_PLUGIN_ROOT is set for every plugin hook Muse runs [measured with `muse plugins hook test`];
# Claude Code sets CLAUDECODE in the shells it starts and CLAUDE_PLUGIN_ROOT for plugin servers.
HARNESSES: tuple[Harness, ...] = (
    Harness(
        id="muse_code",
        label="Muse Code",
        reader="muse-code",
        env_markers=("MUSE_PLUGIN_ROOT",),
        stop_cadence=StopCadence.END_OF_SESSION,
        find_sessions=_muse_sessions,
        sessions_live_in=_muse_sessions_live_in,
        plugin_setup=(
            ("muse", "plugins", "marketplace", "add", "ai-symbiont", PLUGIN_SOURCE),
            ("muse", "plugins", "install", "symbiont@ai-symbiont"),
            ("muse", "plugins", "approve", "symbiont"),
        ),
    ),
    Harness(
        id="claude_code",
        label="Claude Code",
        reader="claude-code",
        env_markers=("CLAUDECODE", "CLAUDE_PLUGIN_ROOT"),
        stop_cadence=StopCadence.EVERY_TURN,
        find_sessions=_claude_sessions,
        sessions_live_in=_claude_sessions_live_in,
        plugin_setup=(
            ("claude", "plugin", "marketplace", "add", PLUGIN_SOURCE),
            ("claude", "plugin", "install", "symbiont@ai-symbiont"),
        ),
    ),
)


def in_reading_order(known: Sequence[Harness] = HARNESSES) -> list[Harness]:
    """The harnesses by label, for output a developer reads; detection order stays in HARNESSES."""
    return sorted(known, key=lambda entry: entry.label)


def harness(harness_id: str, known: Sequence[Harness] = HARNESSES) -> Harness:
    """The registered harness with this id; an unknown id raises, it never defaults."""
    for entry in known:
        if entry.id == harness_id:
            return entry
    ids = ", ".join(entry.id for entry in known)
    raise UnknownHarnessError(f"unknown harness {harness_id!r}; known: {ids}")


def detect(environ: Mapping[str, str], known: Sequence[Harness] = HARNESSES) -> Harness | None:
    """The harness whose marker the environment carries, in registry order; None when none."""
    for entry in known:
        if any(marker in environ for marker in entry.env_markers):
            return entry
    return None


def harness_for_reader(reader: str, known: Sequence[Harness] = HARNESSES) -> str | None:
    """The id of the harness a reader name belongs to; None for datasets that are no harness."""
    return next((entry.id for entry in known if entry.reader == reader), None)


def labels_and(known: Sequence[Harness] = HARNESSES) -> str:
    """The labels as prose: "Claude Code and Muse Code"."""
    return _joined([entry.label for entry in known], "and")


def labels_or(known: Sequence[Harness] = HARNESSES) -> str:
    """The labels as prose with a choice: "Claude Code or Muse Code"."""
    return _joined([entry.label for entry in known], "or")


def _joined(words: list[str], joiner: str) -> str:
    """Labels in alphabetical order: the registry order is detection order, not reading order."""
    words = sorted(words)
    if len(words) < 2:
        return "".join(words)
    return f"{', '.join(words[:-1])} {joiner} {words[-1]}"
