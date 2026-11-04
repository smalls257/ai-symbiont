"""`symbiont repo mine`: start the service's mining job, open the dashboard on it, follow it.

This is a client: it finds the logs, asks the service (which owns the store) to mine them and
reports the service's progress. The opener and the service call are injected, so a test opens no
browser and starts no service.
"""

import argparse
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.readers.claude_code import session_logs
from symbiont.readers.muse_code import muse_store_root
from symbiont.readers.muse_code import session_logs as muse_session_logs
from symbiont.service.asking import AskService, ServiceAnswerError, ServiceUnavailableError
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import read_dashboard_settings

CLAUDE_CODE_READER = "claude-code"
MUSE_CODE_READER = "muse-code"
POLL_S = 0.5
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


def mine_past_sessions(args: argparse.Namespace, registry: RepoRegistry, client: MineClient) -> int:
    """Mine this repository's Claude Code and Muse Code sessions; refuses until it is allowed."""
    if registry.stance(args.project) is not RepoStance.GIVEN:
        sys.stderr.write(
            f"symbiont repo mine: run `symbiont repo allow` for {args.project} first\n"
        )
        return 1
    found = {
        CLAUDE_CODE_READER: session_logs(args.repo_dir, Path.home()),
        MUSE_CODE_READER: muse_session_logs(
            args.repo_dir, muse_store_root(os.environ, Path.home())
        ),
    }
    if not any(found.values()):
        _say(
            f"no Claude Code or Muse Code sessions found for {args.repo_dir.resolve()}; "
            f"looked in {Path.home() / '.claude' / 'projects'} and "
            f"{muse_store_root(os.environ, Path.home()) / 'muse' / 'sessions'}"
        )
        return 0
    sources = [[reader, str(log)] for reader, logs in found.items() for log in logs]
    try:
        started = client.ask("/mine", {"project": args.project, "sources": sources}, args.port)
    except ServiceUnavailableError as offline:
        _say(f"symbiont offline: {offline}")
        return 1
    except ServiceAnswerError as refused:
        sys.stderr.write(f"symbiont repo mine: {refused}\n")
        return 1
    if not started["started"]:
        _say(f"{args.project} is already being mined; following it")
    _show_dashboard(args, client)
    counts = ", ".join(f"{len(logs)} {reader} sessions" for reader, logs in found.items())
    return _follow(args, client, counts)


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


def _ended(progress: dict[str, Any], counts: str) -> int:
    """Report a finished or failed job."""
    if progress["state"] == "failed":
        sys.stderr.write(f"symbiont repo mine: mining failed: {progress['error']}\n")
        return 1
    _say(f"learned {progress['lessons']} lessons from {counts}; they stay on this computer")
    return 0


def _say(line: str) -> None:
    """Print a line for the developer."""
    sys.stdout.write(line + "\n")
