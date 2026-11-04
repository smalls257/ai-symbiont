"""The commands a developer runs from `/symbiont`: answer for a repository, see, silence, forget.

They live beside the service because they read and write what it owns: the answers, the
lessons and the event log. `cli.py` hands in the data directory and how to ask the running
service, so this package imports no client.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.core.notes import happened
from symbiont.miner.lesson_context import AppliesTo, LessonContext, Priority
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.trained import lesson_id
from symbiont.service.asking import AskService, ServiceAnswerError, ServiceUnavailableError
from symbiont.service.events import checker_sentences, last_note_event
from symbiont.service.lesson_list import lesson_lines
from symbiont.service.lesson_lookup import project_of_lesson
from symbiont.service.mine_command import MineClient, dashboard_url, mine_past_sessions
from symbiont.service.pr_learning import PR_INSTRUCTIONS
from symbiont.service.supersessions import superseded_sentences
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import (
    read_correction_settings,
    read_dashboard_settings,
    write_correction_setting,
    write_dashboard_setting,
)


@dataclass(frozen=True)
class Defaults:
    """What the command line decides for these commands: the data directory and the port."""

    data_dir: Path
    port: int


OPEN_DASHBOARD = "open_dashboard_on_mine"
COMMANDS = frozenset(
    {
        "repo",
        "status",
        "why",
        "mute",
        "forget",
        "lessons",
        "context",
        "dashboard",
        "settings",
        "learn-from-prs",
    }
)


def _add_repo_parser(commands: Any, defaults: Defaults) -> None:
    """Register `repo`: the answer for a repository, and mining its past sessions."""
    repo = commands.add_parser(
        "repo", help="answer for this repository: allow, decline, show, mine"
    )
    repo.add_argument("action", choices=["allow", "decline", "show", "mine", "reset"])
    repo.add_argument("--repo-dir", type=Path, default=Path.cwd())
    repo.add_argument("--port", type=int, default=defaults.port)
    repo.add_argument(
        "--no-open", action="store_true", help="mine: print the dashboard address, do not open it"
    )


def add_repo_commands(commands: Any, defaults: Defaults) -> None:
    """Register `repo`, `status`, `why`, `mute`, `forget` and `lessons`."""
    _add_repo_parser(commands, defaults)
    for name, helped in [
        ("status", "what symbiont is doing for this repository"),
        ("why", "why the last note fired"),
        ("mute", "silence the kind of trouble the last note was about"),
        ("forget", "delete the lessons behind the last note (or --lesson ID) and silence them"),
        ("lessons", "list this repository's stored lessons with their ids"),
        (
            "learn-from-prs",
            "print the steps for the session's model to learn from recent PR reviews and CI "
            "failures (symbiont itself reads nothing from GitHub)",
        ),
    ]:
        command = commands.add_parser(name, help=helped)
        if name == "lessons":
            command.add_argument("--all", action="store_true", help="also list dismissed lessons")
        if name == "forget":
            command.add_argument("--lesson", help="an id from `symbiont lessons`")
        if name == "status":
            command.add_argument("--port", type=int, default=defaults.port)
    words = commands.add_parser("context", help="add your own words to a lesson")
    words.add_argument("action", choices=["add"])
    words.add_argument("lesson", help='an id from `symbiont lessons`, or "last"')
    words.add_argument("text", help="what symbiont should say about it, in your words")
    words.add_argument("--intentional", action="store_true", help="the failure is on purpose")
    words.add_argument("--priority", choices=[p.value for p in Priority], default="normal")
    words.add_argument("--terms", default="", help="comma-separated words this applies to")
    words.add_argument("--areas", default="", help="comma-separated path prefixes it applies to")
    dashboard = commands.add_parser("dashboard", help="print this repository's dashboard address")
    dashboard.add_argument("--port", type=int, default=defaults.port)
    setting = commands.add_parser("settings", help="show or switch correction-finding settings")
    setting.add_argument("action", choices=["show", "set"])
    setting.add_argument(
        "name", nargs="?", help=f"claude_code, muse_code, cross_harness or {OPEN_DASHBOARD}"
    )
    setting.add_argument("value", nargs="?", choices=["true", "false"])
    for parser in (commands.choices[name] for name in COMMANDS):
        parser.add_argument("--project", default=Path.cwd().name, help="defaults to this directory")
        parser.add_argument("--data-dir", type=Path, default=defaults.data_dir)


def run_repo_command(args: argparse.Namespace, ask: AskService, client: MineClient) -> int:
    """Run one of COMMANDS; returns the exit code. `ask` reaches the running service.

    `client` is how `repo mine` reaches the service, the browser and the clock.
    """
    try:
        if args.command == "status":
            return _status(args, ask)
        if args.command == "repo" and args.action == "mine":
            return mine_past_sessions(args, RepoRegistry(args.data_dir), client)
        return _COMMANDS[args.command](args)
    except (OSError, ValueError, LookupError) as failed:
        sys.stderr.write(f"symbiont {args.command}: {failed}\n")
        return 1


def _repo(args: argparse.Namespace) -> int:
    """Record or show the answer for the repository."""
    registry = RepoRegistry(args.data_dir)
    if args.action == "show":
        stance = registry.stance(args.project)
        _say(f"{args.project}: {'not asked yet' if stance is None else stance.value}")
    elif args.action == "reset":
        registry.forget_project(args.project)
        _say(f"{args.project}: forgotten; symbiont will ask again at the next session start")
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
        "and Muse Code sessions. To find your past corrections, the model running your session "
        "reads short excerpts of past messages from the same tool's history."
    )


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
    night = _nightly_phrase(state["nightly"])
    return (
        f"symbiont is running. {state['project']}: {repo[state['repo']]}; "
        f"{state['lessons']} stored lessons; {state['muted']} silenced kinds of note; {night}."
    )


def _nightly_phrase(nightly: Any) -> str:
    """The nightly state in words; a service from before the three states answered yes or no."""
    if isinstance(nightly, dict):
        return f"nightly training: {nightly['sentence']}"
    return "its nightly training is live" if nightly else "no nightly training yet"


def _why(args: argparse.Namespace) -> int:
    """Why the last note of this repository fired, from the event log."""
    event = last_note_event(args.data_dir / "runs", args.project)
    set_aside = superseded_sentences(args.data_dir / "runs", args.project)
    if event is None:
        _say(f"no note has been shown for {args.project} yet")
        _say_all(set_aside)
        return 0
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(event["ts"]))
    _say(f"Last note, {when}, after {event['hook']}:")
    for note in event["notes"]:
        _say(f"  {note}")
    _say(_cause_of(event))
    _say_all(checker_sentences(event))
    _say_all(set_aside)
    _say(
        "Silence this kind of note with `symbiont mute`; delete its lessons with `symbiont forget`."
    )
    return 0


def _say_all(sentences: list[str]) -> None:
    """Each sentence on its own line."""
    for sentence in sentences:
        _say(sentence)


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
    if args.lesson is not None and _forgot_written(args, store):
        return 0
    trouble = _trouble_chosen(args, store)
    deleted = store.catalog.forget(args.project, trouble)
    RepoRegistry(args.data_dir).mute(args.project, (trouble.signal.value, *trouble.key))
    _say(f"forgot {deleted} lesson(s) because {happened(trouble)}; they stay silenced if re-mined.")
    return 0


def _forgot_written(args: argparse.Namespace, store: Store) -> bool:
    """Delete the written lesson `--lesson` names, if it is one of this repository's."""
    found = store.curation.find_authored(args.lesson)
    if found is None or found[0] != args.project:
        return False
    store.curation.forget_authored(args.project, args.lesson)
    _say(f"forgot the written lesson {args.lesson}: {found[1].text[:60]}")
    return True


def _trouble_chosen(args: argparse.Namespace, store: Store) -> Signature:
    """The trouble of `--lesson ID`, else of the last note."""
    if args.lesson is None:
        return _last_trouble(args)
    for lesson in store.lessons(args.project):
        if lesson_id(lesson) == args.lesson:
            return lesson.pain_point.signature
    raise LookupError(f"no lesson {args.lesson} in {args.project}; see `symbiont lessons`")


def _context(args: argparse.Namespace) -> int:
    """Store the developer's words for a lesson (an id, or "last"); says which one it picked."""
    store = Store.open(args.data_dir / "store.db")
    wanted = _newest_lesson_id(args, store) if args.lesson == "last" else args.lesson
    project = project_of_lesson(store, wanted)
    if project is None:
        raise LookupError(f"no lesson {wanted}; see `symbiont lessons`")
    applies = AppliesTo(_listed(args.terms), _listed(args.areas))
    words = LessonContext(args.text.strip(), args.intentional, Priority(args.priority), applies)
    store.contexts.save(wanted, project, words)
    _say(f"saved for {wanted} ({_described(store, wanted)}).")
    return 0


def _described(store: Store, ident: str) -> str:
    """What a lesson is about, in a clause: the trouble, or the written text."""
    mined = store.catalog.find(ident)
    if mined is not None:
        return happened(mined[1].pain_point.signature)
    written = store.curation.find_authored(ident)
    return "written lesson: " + (written[1].text[:60] if written else ident)


def _dashboard(args: argparse.Namespace) -> int:
    """Print the dashboard address for this repository."""
    _say(dashboard_url(args.project, args.port))
    return 0


def _settings(args: argparse.Namespace) -> int:
    """Show, or switch, the correction-finding histories and whether mining opens the dashboard."""
    if args.action == "set":
        if args.name is None or args.value is None:
            raise ValueError("settings set needs a name and true or false")
        switched = args.value == "true"
        if args.name == OPEN_DASHBOARD:
            write_dashboard_setting(args.data_dir, open_on_mine=switched)
        else:
            write_correction_setting(args.data_dir, args.name, value=switched)
    current = read_correction_settings(args.data_dir)
    _say(
        f"corrections: claude_code={current.claude_code} muse_code={current.muse_code} "
        f"cross_harness={current.cross_harness}"
    )
    _say(f"dashboard: open_dashboard_on_mine={read_dashboard_settings(args.data_dir).open_on_mine}")
    return 0


def _listed(commas: str) -> tuple[str, ...]:
    """A comma-separated option as a tuple of non-empty items."""
    return tuple(item.strip() for item in commas.split(",") if item.strip())


def _newest_lesson_id(args: argparse.Namespace, store: Store) -> str:
    """The lesson behind the last note, else the newest stored lesson of this repository."""
    event = last_note_event(args.data_dir / "runs", args.project)
    refs = [] if event is None else event.get("records", [])
    if event is not None and event.get("trouble") and refs:
        behind = f"{refs[0][0]}:{refs[0][1]}:{event['trouble'][0]}"
        if store.catalog.find(behind) is not None:
            return behind
    lessons = store.lessons(args.project)
    if lessons:
        return lesson_id(lessons[-1])
    written = store.curation.authored(args.project)
    if not written:
        raise LookupError(f"{args.project} has no stored lessons; try `symbiont repo mine`")
    return written[-1].ident


def _lessons(args: argparse.Namespace) -> int:
    """One line per active lesson, mined or written: id, source and what it says.

    Dismissed (silenced) lessons are hidden unless `--all`, which flags them.
    """
    store = Store.open(args.data_dir / "store.db")
    lines = lesson_lines(store, args.project)
    shown = [line for line in lines if args.all or not line.dismissed]
    for line in shown:
        flags = ("  [dismissed]" if line.dismissed else "") + (
            "  [your words added]" if line.has_words else ""
        )
        _say(f"{line.ident}  {line.source:<10}  {line.text}{flags}")
    hidden = len(lines) - len(shown)
    if hidden:
        _say(f"{hidden} dismissed lesson(s) hidden; `symbiont lessons --all` shows them")
    if not lines:
        _say(f"no stored lessons for {args.project}; try `symbiont repo mine`")
    return 0


def _learn_from_prs(args: argparse.Namespace) -> int:
    """Print what the session's model should do; symbiont reaches no network (CLAUDE.md rule 3)."""
    _say(PR_INSTRUCTIONS)
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
    "learn-from-prs": _learn_from_prs,
    "context": _context,
    "dashboard": _dashboard,
    "settings": _settings,
}
