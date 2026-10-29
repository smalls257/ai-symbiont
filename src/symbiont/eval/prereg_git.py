"""Periphery of the prereg guard: the git adapter, `require_frozen` and the scored-run switch."""

import logging
import subprocess
from pathlib import Path

from symbiont.eval.prereg import (
    FrozenPrereg,
    GitView,
    PathState,
    PreregNotFrozenError,
    verify_frozen,
)

log = logging.getLogger("prereg")
EXPLORATORY = "exploratory"
SCORED = "scored"


class GitCli:
    """`git` run in the directory that holds the prereg; any git failure is a refusal."""

    def __init__(self, anchor: Path) -> None:
        self._cwd = anchor if anchor.is_dir() else anchor.parent

    def _git(self, *args: str, path: Path) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(self._cwd), *args],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise PreregNotFrozenError(path, f"git could not run: {exc}") from exc

    def _out(self, *args: str, path: Path) -> str:
        done = self._git(*args, path=path)
        if done.returncode != 0:
            raise PreregNotFrozenError(path, f"git {args[0]} failed: {done.stderr.strip()}")
        return done.stdout

    def root(self) -> Path:
        """The repository root."""
        return Path(self._out("rev-parse", "--show-toplevel", path=self._cwd).strip())

    def state(self, path: Path) -> PathState:
        """Untracked, staged, modified or clean, from `ls-files` and `status --porcelain`."""
        target = str(path.resolve())
        if self._git("ls-files", "--error-unmatch", "--", target, path=path).returncode != 0:
            return PathState.UNTRACKED
        porcelain = self._out("status", "--porcelain=v1", "--", target, path=path)
        if not porcelain.strip():
            return PathState.CLEAN
        return PathState.STAGED if porcelain[0] != " " else PathState.MODIFIED

    def adding_commit(self, path: Path) -> str:
        """The oldest commit that added the file."""
        shas = self._out(
            "log", "--diff-filter=A", "--format=%H", "--", str(path.resolve()), path=path
        ).split()
        if not shas:
            raise PreregNotFrozenError(path, "no commit adds this file")
        return shas[-1]


def require_frozen(path: str | Path, git: GitView | None = None) -> FrozenPrereg:
    """Return the path, adding commit and sha256 of a committed, unchanged prereg, else raise."""
    target = Path(path)
    if not target.is_file():
        raise PreregNotFrozenError(target, "no such file")
    return verify_frozen(target, git or GitCli(target.resolve()), Path.read_bytes)


def run_provenance(*, scored: bool, prereg: str | None, expects: str) -> dict[str, str | None]:
    """Result-file fields for a run: frozen prereg facts if scored, an exploratory label if not."""
    if not scored:
        if prereg:
            raise PreregNotFrozenError(prereg, "--prereg given without --scored")
        log.warning("EXPLORATORY run: no frozen prereg, not a scored result")
        return {
            "prereg": None,
            "freeze_commit": None,
            "prereg_sha256": None,
            "run_label": EXPLORATORY,
        }
    if not prereg:
        raise PreregNotFrozenError("(none)", "--scored needs --prereg <file>")
    frozen = require_frozen(prereg)
    if frozen.original.name != expects:
        raise PreregNotFrozenError(prereg, f"this runner is registered under {expects}")
    log.info("SCORED run under %s (commit %s)", frozen.path.name, frozen.commit)
    return {
        "prereg": f"prereg/{frozen.path.name}",
        "freeze_commit": frozen.commit,
        "prereg_sha256": frozen.sha256,
        "run_label": SCORED,
    }
