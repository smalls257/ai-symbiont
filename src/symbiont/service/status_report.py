"""`symbiont status`: what the service says about this repository, and the training job's progress.

The job file is read here, not asked of the service: a job runs in its own process and the service
may be down while it trains.
"""

import argparse
import sys
from typing import Any

from symbiont.service.asking import AskService, ServiceAnswerError, ServiceUnavailableError
from symbiont.service.nightly_job import job_sentence


def say(line: str) -> None:
    """Print one line."""
    sys.stdout.write(line + "\n")


def status_report(args: argparse.Namespace, ask: AskService) -> int:
    """What the service says about this repository, or that it is offline."""
    try:
        state = ask("/status", {"project": args.project}, args.port)
    except ServiceUnavailableError as offline:
        say(f"symbiont offline: {offline}")
        say_training(args)
        return 0
    except ServiceAnswerError as unusable:
        sys.stderr.write(f"symbiont status: {unusable}\n")
        return 1
    say(status_lines(state))
    say_training(args)
    return 0


def say_training(args: argparse.Namespace) -> None:
    """The background training job's progress, when one was ever started here."""
    training = job_sentence(args.data_dir / "nightly", args.project)
    if training is not None:
        say(training + ".")


def status_lines(state: dict[str, Any]) -> str:
    """The service's answer as sentences."""
    repo = {"given": "on", "declined": "off (you declined)", "unasked": "not answered yet"}
    night = nightly_phrase(state["nightly"])
    return (
        f"symbiont is running. {state['project']}: {repo[state['repo']]}; "
        f"{state['lessons']} stored lessons; {state['muted']} silenced kinds of note; {night}."
    )


def nightly_phrase(nightly: Any) -> str:
    """The nightly state in words; a service from before the three states answered yes or no."""
    if isinstance(nightly, dict):
        return f"nightly training: {nightly['sentence']}"
    return "its nightly training is live" if nightly else "no nightly training yet"
