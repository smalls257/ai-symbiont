"""The directory names a repository's checkouts go by, so edits made in any of them count.

The miner learns a codebase only by directory name. Agents work in the registered checkout, in
its `git worktree` checkouts and in sibling directories (`<project>-feature`), and a fix made in
any of those is a fix to the codebase. Git is asked here, in the periphery; the miner stays pure.
"""

import logging
import subprocess
from pathlib import Path

from symbiont.store.repos import RepoRegistry

log = logging.getLogger("symbiont.checkouts")


def checkout_names(checkout: Path) -> frozenset[str]:
    """The names of `checkout`, its registered git worktrees and its `<name>-*` siblings.

    A directory that is gone yields no names (and a warning), never a guess.
    """
    if not checkout.is_dir():
        log.warning("checkout %s is not a directory; its worktrees are not known", checkout)
        return frozenset()
    names = {checkout.name, *(path.name for path in _worktrees(checkout))}
    names |= {
        sibling.name
        for sibling in checkout.parent.iterdir()
        if sibling.is_dir() and sibling.name.startswith(f"{checkout.name}-")
    }
    return frozenset(names)


def names_for(registry: RepoRegistry | None, project: str) -> frozenset[str]:
    """The checkout names of `project`'s registered checkout; none while no checkout is known."""
    registered = registry.checkout(project) if registry is not None else None
    return checkout_names(registered) if registered is not None else frozenset()


def _worktrees(checkout: Path) -> list[Path]:
    """What `git worktree list` reports for `checkout`; empty (with a warning) when git cannot."""
    try:
        done = subprocess.run(
            ["git", "-C", str(checkout), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        log.warning("git could not run for %s: %s; worktrees are not known", checkout, exc)
        return []
    if done.returncode != 0:
        log.warning(
            "%s is not a git checkout (%s); worktrees are not known", checkout, done.stderr.strip()
        )
        return []
    return [
        Path(line.removeprefix("worktree "))
        for line in done.stdout.splitlines()
        if line.startswith("worktree ")
    ]
