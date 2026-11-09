"""Which project a Claude Code hook belongs to when its cwd is a subdirectory.

Claude Code's cwd follows the shell, so a hook can fire from `repo/src` while the developer
answered for `repo`. Muse Code always starts at the repository root and passes no known
projects here, so its names never change.
"""

import json
from collections.abc import Callable
from pathlib import Path

from symbiont.store.repos import REGISTRY_FILE


class RegistryUnreadableError(ValueError):
    """repos.json exists but is not a registry of projects; the message names the file."""


def git_root(start: Path) -> Path | None:
    """The nearest directory at or above `start` that holds a `.git`, or None."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def project_for(
    cwd: str | None,
    fallback: str,
    known: frozenset[str],
    root_of: Callable[[Path], Path | None] = git_root,
) -> str:
    """The cwd's folder name, unless that is unknown and the git root above it is known.

    A cwd whose own name is known always wins; with no cwd the fallback stands.
    """
    if not cwd:
        return fallback
    name = Path(cwd).name
    if name in known or not known:
        return name
    root = root_of(Path(cwd))
    return root.name if root is not None and root.name in known else name


def known_projects(data_dir: Path) -> frozenset[str]:
    """Every project the developer answered for; none when nothing was ever recorded."""
    path = data_dir / REGISTRY_FILE
    if not path.exists():
        return frozenset()
    try:
        projects = json.loads(path.read_text(encoding="utf-8"))["projects"]
        return frozenset(projects)
    except (ValueError, KeyError, TypeError, OSError) as broken:
        raise RegistryUnreadableError(f"{path} is not a symbiont registry: {broken}") from broken
