"""The commands a developer runs from `/symbiont`: answer for a repository, see, silence, forget.

They live beside the service because they read and write what it owns: the answers, the
lessons and the event log. `cli.py` hands in the data directory and how to ask the running
service, so this package imports no client.
"""

import argparse
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.core.notes import happened
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.trained import lesson_id
from symbiont.readers import READERS
from symbiont.readers.claude_code import session_logs
from symbiont.readers.muse_code import session_logs as muse_session_logs
from symbiont.service.events import last_note_event
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, remine
from symbiont.store.repos import RepoRegistry, RepoStance

AskService = Callable[[str, dict[str, object], int], dict[str, Any]]


@dataclass(frozen=True)
class Defaults:
    """What the command line decides for these commands: the data directory and the port."""

    data_dir: Path
    port: int


class ServiceUnavailableError(ConnectionError):
    """An `AskService` could not reach the running service; the message says where."""


class ServiceAnswerError(RuntimeError):
    """An `AskService` reached the service but got no usable answer; the message says why."""


COMMANDS = frozenset({"repo", "status", "why", "mute", "forget", "lessons"})
CLAUDE_CODE_READER = "claude-code"
MUSE_CODE_READER = "muse-code"


def add_repo_commands(commands: Any, defaults: Defaults) -> None:
    """Register `repo`, `status`, `why`, `mute`, `forget` and `lessons`."""
    repo = commands.add_parser(
        "repo", help="answer for this repository: allow, decline, show, mine"
    )
    repo.add_argument("action", choices=["allow", "decline", "show", "mine", "reset"])
    repo.add_argument("--repo-dir", type=Path, default=Path.cwd())
    for name, helped in [
        ("status", "what symbiont is doing for this repository"),
        ("why", "why the last note fired"),
        ("mute", "silence the kind of trouble the last note was about"),
        ("forget", "delete the lessons behind the last note (or --lesson ID) and silence them"),
        ("lessons", "list this repository's stored lessons with their ids"),
    ]:
        command = commands.add_parser(name, help=helped)
        if name == "forget":
            command.add_argument("--lesson", help="an id from `symbiont lessons`")
        if name == "status":
            command.add_argument("--port", type=int, default=defaults.port)
    for parser in (commands.choices[name] for name in COMMANDS):
        parser.add_argument("--project", default=Path.cwd().name, help="defaults to this directory")
        parser.add_argument("--data-dir", type=Path, default=defaults.data_dir)


def run_repo_command(args: argparse.Namespace, ask: AskService) -> int:
    """Run one of COMMANDS; returns the exit code. `ask` reaches the running service."""
    try:
        if args.command == "status":
            return _status(args, ask)
        return _COMMANDS[args.command](args)
    except (OSError, ValueError, LookupError) as failed:
        sys.stderr.write(f"symbiont {args.command}: {failed}\n")
        return 1


def _repo(args: argparse.Namespace) -> int:
    """Record or show the answer for the repository; `mine` learns from its past sessions."""
    registry = RepoRegistry(args.data_dir)
    if args.action == "show":
        stance = registry.stance(args.project)
        _say(f"{args.project}: {'not asked yet' if stance is None else stance.value}")
    elif args.action == "reset":
        registry.forget_project(args.project)
        _say(f"{args.project}: forgotten; symbiont will ask again at the next session start")
    elif args.action == "mine":
        return _mine_past_sessions(args, registry)
    else:
        stance = RepoStance.GIVEN if args.action == "allow" else RepoStance.DECLINED
        registry.record_stance(args.project, stance)
        _say(_answer_message(args.project, stance))
    return 0


def _answer_message(project: str, stance: RepoStance) -> str:
    """What the developer is told after answering."""
    if stance is RepoStance.DECLINED:
        return f"{project}: symbiont stays off here; nothing from it is stored."
    return (
        f"{project}: symbiont is on. Everything stays on this computer. "
        "Run `symbiont repo mine` to learn from this repository's past Claude Code "
        "and Muse Code sessions."
    )


def _mine_past_sessions(args: argparse.Namespace, registry: RepoRegistry) -> int:
    """Mine this repository's Claude Code and Muse Code sessions; refuses until it is allowed."""
    if registry.stance(args.project) is not RepoStance.GIVEN:
        sys.stderr.write(
            f"symbiont repo mine: run `symbiont repo allow` for {args.project} first\n"
        )
        return 1
    found = {
        CLAUDE_CODE_READER: session_logs(args.repo_dir, Path.home()),
        MUSE_CODE_READER: muse_session_logs(args.repo_dir, _muse_store_root()),
    }
    if not any(found.values()):
        _say(f"no Claude Code or Muse Code sessions found for {args.repo_dir.resolve()}")
        return 0
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store.open(args.data_dir / "store.db")
    sources = [
        Source(args.project, reader, str(log)) for reader, logs in found.items() for log in logs
    ]
    lessons = remine(store, args.project, MiningRules(READERS, frozenset()), adding=sources)
    counts = ", ".join(f"{len(logs)} {reader} sessions" for reader, logs in found.items())
    _say(f"learned {len(lessons)} lessons from {counts}; they stay on this computer")
    return 0


def _muse_store_root() -> Path:
    """Where Muse Code keeps its data: the XDG data directory."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _status(args: argparse.Namespace, ask: AskService) -> int:
    """What the service says about this repository, or that it is offline."""
    try:
        state = ask("/status", {"project": args.project}, args.port)
    except ServiceUnavailableError as offline:
        _say(f"symbiont offline: {offline}")
        return 0
    except ServiceAnswerError as unusable:
        sys.stderr.write(f"symbiont status: {unusable}\n")
        return 1
    _say(_status_lines(state))
    return 0


def _status_lines(state: dict[str, Any]) -> str:
    """The service's answer as sentences."""
    repo = {"given": "on", "declined": "off (you declined)", "unasked": "not answered yet"}
    night = "its nightly training is live" if state.get("nightly") else "no nightly training yet"
    return (
        f"symbiont is running. {state['project']}: {repo[state['repo']]}; "
        f"{state['lessons']} stored lessons; {state['muted']} silenced kinds of note; {night}."
    )


def _why(args: argparse.Namespace) -> int:
    """Why the last note of this repository fired, from the event log."""
    event = last_note_event(args.data_dir / "runs", args.project)
    if event is None:
        _say(f"no note has been shown for {args.project} yet")
        return 0
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(event["ts"]))
    _say(f"Last note, {when}, after {event['hook']}:")
    for note in event["notes"]:
        _say(f"  {note}")
    _say(_cause_of(event))
    _say(
        "Silence this kind of note with `symbiont mute`; delete its lessons with `symbiont forget`."
    )
    return 0


def _cause_of(event: dict[str, Any]) -> str:
    """One sentence on what the note rested on."""
    trouble = _trouble_of(event)
    if trouble is None:
        return "It was a recall of earlier work, not a warning about a kind of trouble."
    cited = len(event.get("records", []))
    return f"It fired because {happened(trouble)}; it rests on {cited} earlier record(s)."


def _trouble_of(event: dict[str, Any]) -> Signature | None:
    """The kind of trouble an event names, or None."""
    named = event.get("trouble")
    if not named:
        return None
    return Signature(Signal(named[0]), tuple(named[1:]))


def _last_trouble(args: argparse.Namespace) -> Signature:
    """The kind of trouble behind the last note; LookupError when there is none to act on."""
    event = last_note_event(args.data_dir / "runs", args.project)
    trouble = None if event is None else _trouble_of(event)
    if trouble is None:
        raise LookupError(f"the last note of {args.project} (if any) names no kind of trouble")
    return trouble


def _mute(args: argparse.Namespace) -> int:
    """Silence the kind of trouble the last note was about."""
    trouble = _last_trouble(args)
    RepoRegistry(args.data_dir).mute(args.project, (trouble.signal.value, *trouble.key))
    _say(f"silenced: no more notes because {happened(trouble)}.")
    return 0


def _forget(args: argparse.Namespace) -> int:
    """Delete the lessons behind the last note (or one chosen id) and keep them silenced."""
    store = Store.open(args.data_dir / "store.db")
    trouble = _trouble_chosen(args, store)
    deleted = store.forget_trouble(args.project, trouble)
    RepoRegistry(args.data_dir).mute(args.project, (trouble.signal.value, *trouble.key))
    _say(f"forgot {deleted} lesson(s) because {happened(trouble)}; they stay silenced if re-mined.")
    return 0


def _trouble_chosen(args: argparse.Namespace, store: Store) -> Signature:
    """The trouble of `--lesson ID`, else of the last note."""
    if args.lesson is None:
        return _last_trouble(args)
    for lesson in store.lessons(args.project):
        if lesson_id(lesson) == args.lesson:
            return lesson.pain_point.signature
    raise LookupError(f"no lesson {args.lesson} in {args.project}; see `symbiont lessons`")


def _lessons(args: argparse.Namespace) -> int:
    """One line per stored lesson: its id and what happened."""
    lessons = Store.open(args.data_dir / "store.db").lessons(args.project)
    for lesson in lessons:
        _say(f"{lesson_id(lesson)}  {happened(lesson.pain_point.signature)}")
    if not lessons:
        _say(f"no stored lessons for {args.project}; try `symbiont repo mine`")
    return 0


def _say(line: str) -> None:
    """Print a line for the developer."""
    sys.stdout.write(line + "\n")


_COMMANDS = {
    "repo": _repo,
    "why": _why,
    "mute": _mute,
    "forget": _forget,
    "lessons": _lessons,
}
