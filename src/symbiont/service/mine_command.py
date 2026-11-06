"""`symbiont repo mine`: start the service's mining job, open the dashboard on it, follow it.

This is a client: it finds the logs, asks the service (which owns the store) to mine them and
reports the service's progress. The opener and the service call are injected, so a test opens no
browser and starts no service.
"""

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.readers.harnesses import HARNESSES, Harness, in_reading_order, labels_or
from symbiont.service.asking import AskService, ServiceAnswerError, ServiceUnavailableError
from symbiont.service.wording import counted
from symbiont.store.held_back import held_back_sentence, held_by_reason
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import read_dashboard_settings

POLL_S = 0.5
STAYS_LOCAL = "the lessons and counts stay on this computer"
OpenPage = Callable[[str], bool]


@dataclass(frozen=True)
class MineClient:
    """How the command reaches the world: the service, the browser and the clock."""

    ask: AskService
    open_page: OpenPage
    pause: Callable[[float], None] = time.sleep


def dashboard_url(project: str, port: int) -> str:
    """The address of a repository's dashboard; the project name is percent-encoded."""
    safe = "".join(
        c
        if c.isascii() and (c.isalnum() or c in "-._~")
        else "".join(f"%{b:02X}" for b in c.encode())
        for c in project
    )
    return f"http://127.0.0.1:{port}/dashboard?project={safe}"


def mining_url(project: str, port: int) -> str:
    """The dashboard address that starts on the Mine stage, even if the job is already done."""
    return dashboard_url(project, port) + "&mining=1"


def mine_past_sessions(
    args: argparse.Namespace,
    registry: RepoRegistry,
    client: MineClient,
    known: Sequence[Harness] = HARNESSES,
) -> int:
    """Mine this repository's sessions in every known harness; refuses until it is allowed."""
    if registry.stance(args.project) is not RepoStance.GIVEN:
        sys.stderr.write(
            f"symbiont repo mine: run `symbiont repo allow` for {args.project} first\n"
        )
        return 1
    home = Path.home()
    found = {
        entry.reader: entry.find_sessions(args.repo_dir, os.environ, home)
        for entry in in_reading_order(known)
    }
    if not any(found.values()):
        _say_nothing_found(args.repo_dir, known, home)
        return 0
    sources = [[reader, str(log)] for reader, logs in found.items() for log in logs]
    try:
        started = client.ask(
            "/mine",
            {"project": args.project, "sources": sources, "repo_dir": str(args.repo_dir.resolve())},
            args.port,
        )
    except ServiceUnavailableError as offline:
        _say(f"symbiont offline: {offline}")
        return 1
    except ServiceAnswerError as refused:
        sys.stderr.write(f"symbiont repo mine: {refused}\n")
        return 1
    if not started["started"]:
        _say(f"{args.project} is already being mined; following it")
    _show_dashboard(args, client)
    return _follow(args, client, _session_counts(found, known))


def _say_nothing_found(repo_dir: Path, known: Sequence[Harness], home: Path) -> None:
    """Say which harnesses were looked for, and where, when no session was found."""
    places = " and ".join(
        str(entry.sessions_live_in(os.environ, home)) for entry in in_reading_order(known)
    )
    _say(f"no {labels_or(known)} sessions found for {repo_dir.resolve()}; looked in {places}")


def _session_counts(found: dict[str, list[Path]], known: Sequence[Harness]) -> str:
    """`1 Claude Code session, 0 Muse Code sessions`: harness labels, not reader ids."""
    labels = {entry.reader: entry.label for entry in known}
    return ", ".join(
        counted(len(logs), f"{labels.get(reader, reader)} session")
        for reader, logs in found.items()
    )


def _show_dashboard(args: argparse.Namespace, client: MineClient) -> None:
    """Print the dashboard address and open it unless the developer said not to."""
    url = mining_url(args.project, args.port)
    _say(f"dashboard: {url}")
    if args.no_open or not read_dashboard_settings(args.data_dir).open_on_mine:
        return
    if not client.open_page(url):
        _say("could not open a browser here; open the address above")


def _follow(args: argparse.Namespace, client: MineClient, counts: str) -> int:
    """Print the job's progress until it ends; the exit code says how it ended."""
    last: tuple[Any, ...] = ()
    try:
        while True:
            progress = client.ask("/mine/progress", {"project": args.project}, args.port)
            seen = (progress["sessions_read"], progress["pain_points"])
            if progress["state"] != "running":
                return _ended(progress, counts)
            if seen != last:
                _say(_progress_line(progress))
                last = seen
            client.pause(POLL_S)
    except KeyboardInterrupt:
        watch = dashboard_url(args.project, args.port)
        _say(f"mining keeps running in the service; watch it at {watch}")
        return 0
    except ServiceUnavailableError as offline:
        sys.stderr.write(f"symbiont repo mine: lost the service while mining: {offline}\n")
        return 1
    except ServiceAnswerError as refused:
        sys.stderr.write(f"symbiont repo mine: {refused}\n")
        return 1


def _progress_line(progress: dict[str, Any]) -> str:
    """One terminal line for a running job."""
    return (
        f"reading sessions {progress['sessions_read']} of {progress['sessions_total']}: "
        f"{progress['pain_points']} pain points so far"
    )


def _held_clause(progress: dict[str, Any]) -> str:
    """`; held back 3: ...; the lessons and counts stay on this computer`, or a note on none."""
    if "held_back" not in progress:
        return f"; the service did not report what it held back; {STAYS_LOCAL}"
    held = held_back_sentence(held_by_reason(progress["held_back"]))
    return f"; {held}; {STAYS_LOCAL}" if held else f"; {STAYS_LOCAL}"


def _ended(progress: dict[str, Any], counts: str) -> int:
    """Report a finished or failed job."""
    if progress["state"] == "failed":
        sys.stderr.write(f"symbiont repo mine: mining failed: {progress['error']}\n")
        return 1
    lessons = counted(progress["lessons"], "lesson")
    _say(f"learned {lessons} from {counts}{_held_clause(progress)}")
    return 0


def _say(line: str) -> None:
    """Print a line for the developer."""
    sys.stdout.write(line + "\n")
