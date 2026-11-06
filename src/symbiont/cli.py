"""The `symbiont` command: serve, recall, mcp, mine, hook <event>, install and uninstall."""

import argparse
import logging
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from symbiont.core.warner import WarnerWeightsError
from symbiont.delivery.hook_main import add_hook_arguments, forward_hook, read_hook_input
from symbiont.delivery.hook_profiles import PROFILES
from symbiont.delivery.hooks import NoteStyle, offline_note
from symbiont.delivery.install.transaction import (
    HarnessInstall,
    InstallError,
    install,
    uninstall,
)
from symbiont.delivery.launch import DEFAULT_DATA_DIR, patient_call
from symbiont.delivery.mcp_operator import operate_in_server
from symbiont.delivery.mcp_server import serve_stdio_operating
from symbiont.delivery.open_page import open_in_browser
from symbiont.delivery.recall import (
    ServiceOfflineError,
    ServiceRefusedError,
    ServiceReplyError,
    call_service,
    recall_answer,
)
from symbiont.delivery.stdio import use_utf8_lf_stdio
from symbiont.readers import READERS
from symbiont.records.privacy import OwnHistoryConsent
from symbiont.service.app import ServiceMode
from symbiont.service.asking import AskService, ServiceAnswerError, ServiceUnavailableError
from symbiont.service.judge_model import JudgeModel, JudgeOfflineError
from symbiont.service.mine_command import MineClient, OpenPage
from symbiont.service.nightly import NightlyJudges, RecallJudges
from symbiont.service.nightly_command import add_nightly_command, run_nightly_command
from symbiont.service.nightly_tools import revive_judge_server
from symbiont.service.operator_commands import (
    COMMANDS,
    Defaults,
    add_repo_commands,
    run_repo_command,
)
from symbiont.service.server import SERVICE_PORT, serve
from symbiont.service.wiring import (
    Guards,
    MemorySetupError,
    load_warner,
    open_memory,
    open_service,
)
from symbiont.store.consent import SETTING, ConsentFileError, read_consent, record_consent
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, coverage_lines, remine
from symbiont.store.repos import RepoRegistry

INSTALLERS = {harness_id: entry.install for harness_id, entry in PROFILES.items()}
HARNESSES = sorted(INSTALLERS)


def main(
    argv: Sequence[str] | None = None,
    *,
    open_page: OpenPage = open_in_browser,
    mine_ask: AskService | None = None,
    mine_pause: Callable[[float], None] = time.sleep,
) -> int:
    """Run one subcommand and return its exit code; tests inject the browser, service and pause."""
    args = _parser().parse_args(argv)
    if args.command in COMMANDS:
        ask = mine_ask or _ask_starting_service(args)
        return run_repo_command(args, _ask_service, MineClient(ask, open_page, mine_pause))
    if args.command == "serve":
        return _serve(args)
    if args.command == "mcp":
        return _mcp(args)
    if args.command == "hook":
        return _hook(args)
    if args.command in ("install", "uninstall"):
        return _installation(args)
    if args.command == "mine":
        return _mine(args)
    if args.command == "consent":
        return _consent(args)
    if args.command == "nightly":
        return run_nightly_command(args, pause=mine_pause)
    return _recall(args)


def _parser() -> argparse.ArgumentParser:
    """The `symbiont` argument parser: `serve` and `recall`."""
    parser = argparse.ArgumentParser(prog="symbiont")
    commands = parser.add_subparsers(dest="command", required=True)
    serving = commands.add_parser("serve", help="run the local service on 127.0.0.1")
    serving.add_argument("--port", type=int, default=SERVICE_PORT)
    serving.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    serving.add_argument(
        "--mode", type=ServiceMode, choices=list(ServiceMode), default=ServiceMode.WARN_AND_RECALL
    )
    serving.add_argument(
        "--warner", type=Path, help="weights from scripts/routea/fit_warner.py; else counters"
    )
    serving.add_argument(
        "--memory-url", help="loopback mlx_lm.server of the memory model (scripts/routea)"
    )
    serving.add_argument(
        "--memory-dir", type=Path, help="what train_memory.py wrote: adapter/ and manifests/"
    )
    _add_judge_options(serving)
    asking = commands.add_parser("recall", help="ask the local service one question")
    asking.add_argument("question")
    asking.add_argument(
        "--project", default=Path.cwd().name, help="defaults to this directory's name"
    )
    asking.add_argument("--port", type=int, default=SERVICE_PORT)
    mcp = commands.add_parser("mcp", help="serve the recall tool over MCP stdio")
    mcp.add_argument("--project", default=Path.cwd().name, help="defaults to this directory's name")
    mcp.add_argument("--port", type=int, default=SERVICE_PORT)
    _add_hook_commands(commands)
    add_repo_commands(commands, Defaults(DEFAULT_DATA_DIR, SERVICE_PORT))
    _add_mine_command(commands)
    add_nightly_command(commands, DEFAULT_DATA_DIR)
    consent = commands.add_parser(
        "consent",
        help="whether lessons from your OWN sessions may reach Spark (default: withheld); "
        "third-party private data never may",
    )
    consent.add_argument("choice", choices=["give", "withdraw", "show"])
    consent.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return parser


def _add_mine_command(commands: Any) -> None:
    """Register `mine`: re-read the project's logs and store its lessons."""
    mining = commands.add_parser(
        "mine", help="re-read a project's logs, store its lessons, print resolution coverage"
    )
    mining.add_argument("--project", default=Path.cwd().name)
    mining.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    mining.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="READER=PATH",
        help=f"register a log; readers: {', '.join(sorted(READERS))}",
    )
    mining.add_argument("--held-out", action="append", default=[], metavar="TASK_ID")


def _mine(args: argparse.Namespace) -> int:
    """Mine the given READER=PATH sources and print the resolution coverage."""
    sources = []
    for spec in args.source:
        reader, _, path = spec.partition("=")
        if not path:
            print(f"symbiont mine: --source must be READER=PATH, got {spec!r}", file=sys.stderr)
            return 1
        sources.append(Source(args.project, reader, path))
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store.open(args.data_dir / "store.db")
    rules = MiningRules(READERS, frozenset(args.held_out))
    try:
        lessons = remine(store, args.project, rules, adding=sources)
    except (OSError, ValueError) as failed:  # unreadable log, unknown reader, held-out task
        print(f"symbiont mine: {failed}", file=sys.stderr)
        return 1
    print(f"{len(lessons)} lessons from {len(store.sources(args.project))} logs")
    print("\n".join(coverage_lines(lessons)))
    return 0


def _add_hook_commands(commands: Any) -> None:
    """Register `hook`, `install` and `uninstall`; the hook reads its event JSON from stdin."""
    hook = commands.add_parser("hook", help="forward one harness hook event (JSON on stdin)")
    add_hook_arguments(hook)
    for name in ("install", "uninstall"):
        setup = commands.add_parser(name, help=f"{name} symbiont's hooks in a project directory")
        setup.add_argument("harness", choices=HARNESSES)
        setup.add_argument("--project-dir", type=Path, default=Path.cwd())
        setup.add_argument(
            "--notes", type=NoteStyle, choices=list(NoteStyle), default=NoteStyle.PLAIN
        )
    commands.choices["install"].add_argument("--yes", action="store_true", help="skip the prompt")


def _ask_starting_service(args: argparse.Namespace) -> AskService:
    """Ask the service for `repo mine`, starting it when it is down: mining needs it to be up."""
    data_dir = getattr(args, "data_dir", DEFAULT_DATA_DIR)
    patient = patient_call(data_dir)

    def ask(route: str, body: dict[str, object], port: int) -> dict[str, Any]:
        """Call the service; its two failures become the operator commands' errors."""
        try:
            return patient(route, body, port)
        except ServiceOfflineError as offline:
            raise ServiceUnavailableError(str(offline)) from offline
        except (ServiceRefusedError, ServiceReplyError) as unusable:
            raise ServiceAnswerError(str(unusable)) from unusable

    return ask


def _ask_service(route: str, body: dict[str, object], port: int) -> dict[str, Any]:
    """Ask the running service; the two ways it can fail become the operator commands' errors."""
    try:
        return call_service(route, body, port)
    except ServiceOfflineError as offline:
        raise ServiceUnavailableError(str(offline)) from offline
    except (ServiceRefusedError, ServiceReplyError) as unusable:
        raise ServiceAnswerError(str(unusable)) from unusable


def _add_judge_options(serving: argparse.ArgumentParser) -> None:
    """The agree rule's first-night judge servers and the nightly records."""
    serving.add_argument(
        "--judge-url",
        help="loopback plug_judge_server.py with the 3 round-3 adapters (first night)",
    )
    serving.add_argument(
        "--nightly-dir",
        type=Path,
        help="per-repository nightly records (default DATA/nightly, always read: no flag needed)",
    )


def _serve(args: argparse.Namespace) -> int:
    """Start the local service with the optional warner and memory model; bad setup exits 1."""
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="symbiont-service: %(message)s"
    )
    if (args.memory_url is None) != (args.memory_dir is None):
        print("symbiont serve: --memory-url and --memory-dir go together", file=sys.stderr)
        return 1
    try:
        warner = load_warner(args.warner) if args.warner else None
        memory = None
        if args.memory_url:
            memory = open_memory(args.memory_url, args.memory_dir)
        judge = JudgeModel(args.judge_url) if args.judge_url else None
        nightly = NightlyJudges(
            args.nightly_dir or args.data_dir / "nightly", revive=revive_judge_server
        )
        service = open_service(
            args.data_dir,
            args.mode,
            warner,
            memory,
            Guards(
                RecallJudges(judge, nightly),
                RepoRegistry(args.data_dir),
                nightly,
            ),
        )
    except (
        OSError,
        WarnerWeightsError,
        MemorySetupError,
        ConsentFileError,
        JudgeOfflineError,
    ) as unusable:
        print(f"symbiont serve: {unusable}", file=sys.stderr)
        return 1
    serve(service, args.port)
    return 0


def _consent(args: argparse.Namespace) -> int:
    """Show the own-history consent, recording a give or withdraw first."""
    chosen = {"give": OwnHistoryConsent.GIVEN, "withdraw": OwnHistoryConsent.WITHHELD}
    try:
        if args.choice in chosen:
            record_consent(args.data_dir, chosen[args.choice])
        current = read_consent(args.data_dir)
    except ConsentFileError as unusable:
        print(f"symbiont consent: {unusable}", file=sys.stderr)
        return 1
    print(f"{SETTING} = {current.value} (restart symbiont serve to apply)")
    return 0


def _mcp(args: argparse.Namespace) -> int:
    """Serve recall, the curation tools and the operator tools over stdio, logging to stderr."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="symbiont-mcp: %(message)s")
    use_utf8_lf_stdio()
    serve_stdio_operating(sys.stdin, sys.stdout, args.project, args.port, operate_in_server(main))
    return 0


def _recall(args: argparse.Namespace) -> int:
    """Print the service's answer, or `symbiont offline: ...` when it is down."""
    try:
        print(recall_answer(args.question, args.project, args.port))
    except ServiceOfflineError as offline:
        print(offline_note(offline))
        return 0
    except ServiceRefusedError as refused:
        print(f"symbiont refused the question: {refused}", file=sys.stderr)
        return 1
    except ServiceReplyError as unusable:
        print(f"symbiont got no usable answer: {unusable}", file=sys.stderr)
        return 1
    return 0


def _hook(args: argparse.Namespace) -> int:
    """Forward one hook event; a down service prints the offline notice, not an empty note."""
    return forward_hook(args, read_hook_input())


def _installation(args: argparse.Namespace) -> int:
    """Install or uninstall hooks for the chosen harness, showing the diff first."""
    spec: HarnessInstall = INSTALLERS[args.harness](args.notes)
    try:
        if args.command == "uninstall":
            uninstall(spec, args.project_dir)
            print(f"symbiont hooks removed from {args.project_dir}")
        else:
            print(
                "note: hooks call `symbiont`, which must be on PATH (for example uv tool install)"
            )
            approve = _approve_all if args.yes else _ask_before_writing
            print(install(spec, args.project_dir, approve).value)
    except InstallError as failed:
        print(f"symbiont {args.command}: {failed}", file=sys.stderr)
        return 1
    return 0


def _approve_all(diff: str) -> bool:
    """Print the diff and accept it, for non-interactive installs."""
    print(diff)
    return True


def _ask_before_writing(diff: str) -> bool:
    """Print the diff and write only on an explicit `y`."""
    print(diff)
    return input("Write these changes? [y/N] ").strip().lower() == "y"


if __name__ == "__main__":
    sys.exit(main())
