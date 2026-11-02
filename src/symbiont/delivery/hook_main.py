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

from symbiont.delivery.hooks import (
    AUTO,
    CLAUDE_CODE,
    MUSE_CODE,
    HookEvent,
    HookInputError,
    HookSettings,
    NoteStyle,
    resolve_harness,
    run_hook,
)
from symbiont.delivery.launch import DEFAULT_DATA_DIR, reviving_call
from symbiont.delivery.recall import ServiceRefusedError, ServiceReplyError
from symbiont.egress.policy import LOCAL_SERVICE_PORT

HARNESS_CHOICES = (AUTO, CLAUDE_CODE, MUSE_CODE)


def add_hook_arguments(parser: argparse.ArgumentParser) -> None:
    """The arguments of a hook command: the event, and where and how to forward it."""
    parser.add_argument("event", type=HookEvent, choices=list(HookEvent))
    parser.add_argument("--harness", choices=HARNESS_CHOICES, default=AUTO)
    parser.add_argument("--notes", type=NoteStyle, choices=list(NoteStyle), default=NoteStyle.PLAIN)
    parser.add_argument("--project", default=Path.cwd().name, help="used when the input has no cwd")
    parser.add_argument("--port", type=int, default=LOCAL_SERVICE_PORT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)


def forward_hook(args: argparse.Namespace, stdin_text: str) -> int:
    """Forward one hook event and print what the harness should show; always returns 0."""
    harness = resolve_harness(args.harness, os.environ)
    settings = HookSettings(harness, args.notes, args.port, args.project)
    try:
        result = run_hook(args.event, stdin_text, settings, reviving_call(args.data_dir, args.port))
    except (HookInputError, ServiceRefusedError, ServiceReplyError) as unusable:
        sys.stderr.write(f"symbiont hook {args.event}: {unusable}\n")
        said = {"systemMessage": f"symbiont could not use {args.event}: {unusable}"}
        sys.stdout.write(json.dumps(said) + "\n")
        return 0
    if result.warning:
        sys.stderr.write(result.warning + "\n")
    if result.context:
        sys.stdout.write(result.context + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the `symbiont-hook` script."""
    parser = argparse.ArgumentParser(prog="symbiont-hook")
    add_hook_arguments(parser)
    return forward_hook(parser.parse_args(argv), sys.stdin.read())
