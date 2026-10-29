"""How a real domain plugin runs its driver commands: locally, or printed and not run.

A driver that exits non-zero raises `CommandError` naming the command, so a plugin never parses
a half-written log as a round. `PrintingRunner` records and prints, for plans and tests.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class CommandError(RuntimeError):
    """A driver command exited non-zero."""


class CommandRunner(Protocol):
    """Runs one driver command in a directory."""

    def run(self, argv: Sequence[str], cwd: Path) -> None:
        """Raise CommandError on a non-zero exit."""
        ...


@dataclass
class LocalRunner:
    """Runs the command here, output streamed to the caller's terminal and logs."""

    say: Callable[[str], None] = print

    def run(self, argv: Sequence[str], cwd: Path) -> None:
        """Run and wait; raises CommandError naming the command."""
        self.say(f"  run: {shlex.join(argv)} (in {cwd})")
        code = subprocess.run(list(argv), cwd=cwd, check=False).returncode
        if code != 0:
            raise CommandError(f"exit {code}: {shlex.join(argv)}")


@dataclass
class PrintingRunner:
    """Prints what would run, records it, runs nothing."""

    say: Callable[[str], None] = print
    commands: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, argv: Sequence[str], cwd: Path) -> None:
        """Record and print the command."""
        self.commands.append(tuple(argv))
        self.say(f"  would run: {shlex.join(argv)} (in {cwd})")
