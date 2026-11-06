"""The hook command the plugin runs: `symbiont-hook <event>`, also `symbiont hook <event>`.

It runs on every tool call, so it imports no learner or store and starts fast. It exits 0 on
every path and prints one visible line for each failure, never an empty note.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from symbiont.delivery.hook_profiles import ProjectNaming, profile
from symbiont.delivery.hook_trace import record_outcome, record_received, trace_path
from symbiont.delivery.hooks import (
    AUTO,
    HookEvent,
    HookInputError,
    HookSettings,
    NoteStyle,
    NoteVisibility,
    resolve_harness,
    run_hook,
)
from symbiont.delivery.launch import DEFAULT_DATA_DIR, reviving_call
from symbiont.delivery.project_identity import RegistryUnreadableError, known_projects
from symbiont.delivery.recall import ServiceRefusedError, ServiceReplyError
from symbiont.delivery.stdio import use_utf8_lf_stdio
from symbiont.delivery.stop_hook import run_stop
from symbiont.egress.policy import LOCAL_SERVICE_PORT
from symbiont.readers.harnesses import HARNESSES, UnknownHarnessError

HARNESS_CHOICES = (AUTO, *(entry.id for entry in HARNESSES))
UNKNOWN_HARNESS_LINE = (
    "symbiont: cannot tell which harness runs this hook; "
    "reinstall the plugin or pass --harness <id>"
)


def add_hook_arguments(parser: argparse.ArgumentParser) -> None:
    """The arguments of a hook command: the event, and where and how to forward it."""
    parser.add_argument("event", type=HookEvent, choices=list(HookEvent))
    parser.add_argument("--harness", choices=HARNESS_CHOICES, default=AUTO)
    parser.add_argument("--notes", type=NoteStyle, choices=list(NoteStyle), default=NoteStyle.PLAIN)
    parser.add_argument(
        "--visibility",
        type=NoteVisibility,
        choices=list(NoteVisibility),
        default=NoteVisibility.SHOWN,
        help="shown: the developer sees each note (a headline via systemMessage; on Muse Code the "
        "model is also asked to say it in its reply); model-only: the model alone",
    )
    parser.add_argument("--project", default=Path.cwd().name, help="used when the input has no cwd")
    parser.add_argument("--port", type=int, default=LOCAL_SERVICE_PORT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)


def forward_hook(args: argparse.Namespace, stdin_text: str) -> int:
    """Forward one hook event and print what the harness should show; always returns 0."""
    trace = trace_path(os.environ, args.data_dir)
    record_received(trace, args.event, stdin_text)
    try:
        harness = resolve_harness(args.harness, os.environ)
    except UnknownHarnessError:
        return _say_unusable(trace, args.event, UNKNOWN_HARNESS_LINE)
    try:
        names_from_git = profile(harness.id).project_naming is ProjectNaming.GIT_ROOT_WHEN_KNOWN
        known = known_projects(args.data_dir) if names_from_git else frozenset()
        settings = HookSettings(
            harness.id, args.notes, args.port, args.project, args.visibility, known
        )
        call = reviving_call(args.data_dir, args.port)
        if args.event is HookEvent.STOP:
            result = run_stop(stdin_text, settings, call)
        else:
            result = run_hook(args.event, stdin_text, settings, call)
    except (
        HookInputError,
        RegistryUnreadableError,
        ServiceRefusedError,
        ServiceReplyError,
    ) as unusable:
        record_outcome(trace, args.event, "dropped", f"{type(unusable).__name__}: {unusable}")
        sys.stderr.write(f"symbiont hook {args.event}: {unusable}\n")
        said = {"systemMessage": f"symbiont could not use {args.event}: {unusable}"}
        sys.stdout.write(json.dumps(said) + "\n")
        return 0
    if result.warning:
        record_outcome(trace, args.event, "dropped", result.warning)
    else:
        record_outcome(trace, args.event, "forwarded")
    if result.warning:
        sys.stderr.write(result.warning + "\n")
    if result.context:
        sys.stdout.write(result.context + "\n")
    return 0


def _say_unusable(trace: Path | None, event: HookEvent, line: str) -> int:
    """Show a visible line for a hook that cannot run; the harness is never blocked."""
    record_outcome(trace, event, "dropped", line)
    sys.stderr.write(line + "\n")
    sys.stdout.write(json.dumps({"systemMessage": line}) + "\n")
    return 0


def read_hook_input() -> str:
    """The event JSON on stdin, read as UTF-8; the reply goes out as UTF-8 too."""
    use_utf8_lf_stdio()
    return sys.stdin.read()


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the `symbiont-hook` script."""
    parser = argparse.ArgumentParser(prog="symbiont-hook")
    add_hook_arguments(parser)
    return forward_hook(parser.parse_args(argv), read_hook_input())
