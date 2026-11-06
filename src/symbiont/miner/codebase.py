"""Which files belong to the codebase: the one rule churn and fix-finding share.

The miner learns the repository only by name (the directory it lives in), so the rule is about
where a path sits: below a repo-name directory, relative with a directory of its own, or a
top-level file that is the project itself. Temporary and hidden tool directories never count.
"""

_THROWAWAY_DIRS = ("/tmp/", "/var/folders/", "/private/tmp/")
# Top-level files that are the project itself, not a scratch script dropped in the root.
PROJECT_FILES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "conftest.py",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Makefile",
    }
)


def repo_relative(path: str, repo_names: frozenset[str]) -> str | None:
    """`path` relative to the repo root, or None when it is outside the codebase."""
    if path.startswith(_THROWAWAY_DIRS):
        return None
    relative = _below_repo(path, repo_names) if path.startswith("/") else path.removeprefix("./")
    relative = _in_worktree(relative) if relative else relative
    if not relative or relative.startswith("..") or _in_hidden_dir(relative):
        return None
    return relative if "/" in relative or relative in PROJECT_FILES else None


def _below_repo(path: str, repo_names: frozenset[str]) -> str | None:
    """What follows the outermost repo-name directory of an absolute path, else None.

    Outermost because a repo `sqlglot` holds a package `sqlglot`.
    """
    parts = path.split("/")
    inside = [i for i, part in enumerate(parts[:-1]) if part in repo_names]
    return "/".join(parts[inside[0] + 1 :]) if inside else None


def _in_worktree(relative: str) -> str:
    """The path inside a Claude Code worktree (`.claude/worktrees/<name>/...`), else unchanged."""
    parts = relative.split("/")
    return (
        "/".join(parts[3:])
        if parts[:2] == [".claude", "worktrees"] and len(parts) > 3
        else relative
    )


def _in_hidden_dir(relative: str) -> bool:
    """True when a directory of the path starts with a dot (`.claude/plans/x.md`)."""
    return any(part.startswith(".") for part in relative.split("/")[:-1])
