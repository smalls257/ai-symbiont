"""The `symbiont` command: `serve` runs the local service, `recall` asks it one question."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from symbiont.delivery.recall import ServiceOfflineError, ServiceRefusedError, recall_answer
from symbiont.service.app import ServiceMode
from symbiont.service.server import SERVICE_PORT, serve
from symbiont.service.wiring import open_service

DEFAULT_DATA_DIR = Path.home() / ".symbiont"


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand; returns the exit code."""
    args = _parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args)
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
    asking = commands.add_parser("recall", help="ask the local service one question")
    asking.add_argument("question")
    asking.add_argument(
        "--project", default=Path.cwd().name, help="defaults to this directory's name"
    )
    asking.add_argument("--port", type=int, default=SERVICE_PORT)
    return parser


def _serve(args: argparse.Namespace) -> int:
    """Run the local service until interrupted."""
    serve(open_service(args.data_dir, args.mode), args.port)
    return 0


def _recall(args: argparse.Namespace) -> int:
    """Print the service's answer, or `symbiont offline: ...` when it is down."""
    try:
        print(recall_answer(args.question, args.project, args.port))
    except ServiceOfflineError as offline:
        print(f"symbiont offline: {offline}")
        return 0
    except ServiceRefusedError as refused:
        print(f"symbiont refused the question: {refused}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
