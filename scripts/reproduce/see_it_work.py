"""Tier 1 of REPRODUCE.md: replay a recorded failure and fix, then watch the repeat get a note.

Every step is the product's own command against a throwaway home and data directory, and the run
fails unless the returned note names the earlier fix. A designed demo on a synthetic repository,
not a measurement.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "ledger"
RECORDED_SESSION = ROOT / "tests" / "fixtures" / "repro" / "ledger-session.jsonl"
PROJECT = "ledger"
SERVICE_START_WAIT_S = 20.0
# Not the default 7377, so the demo never talks to a service the reader already runs.
DEMO_PORT = 47377
USER_WORDS = "integers in each currency's minor units"


class DemoError(RuntimeError):
    """A demo step failed; the message names the step and carries the command's own output."""


@dataclass(frozen=True)
class Rig:
    """Everything the demo touches, all under one temporary directory."""

    home: Path
    work: Path
    data: Path

    @property
    def environment(self) -> dict[str, str]:
        """The child environment: a fresh home, so no real Claude Code session is ever read."""
        return {**os.environ, "HOME": str(self.home), "XDG_DATA_HOME": str(self.home / ".local")}


def symbiont(rig: Rig, *words: str, stdin: str = "") -> str:
    """Run one `symbiont` subcommand against the rig; raises DemoError with its output."""
    command = [sys.executable, "-m", "symbiont.cli", *words]
    done = subprocess.run(
        command, input=stdin, capture_output=True, text=True, env=rig.environment, check=False
    )
    if done.returncode != 0:
        raise DemoError(f"symbiont {' '.join(words)} failed:\n{done.stdout}{done.stderr}")
    return done.stdout


def say(line: str = "") -> None:
    """One line of the demo's narration."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def claude_code_folder(rig: Rig) -> Path:
    """Where Claude Code would keep this repository's sessions under the rig's home."""
    return rig.home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(rig.work.resolve()))


def lay_out(rig: Rig) -> None:
    """Copy the example repository and put the recorded session where Claude Code keeps it."""
    shutil.copytree(
        EXAMPLE, rig.work, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
    )
    folder = claude_code_folder(rig)
    folder.mkdir(parents=True)
    shutil.copy(RECORDED_SESSION, folder / "session-1.jsonl")


def wait_until_listening(port: int, service: subprocess.Popen[bytes]) -> None:
    """Block until the service accepts connections; DemoError if it exits or is too slow."""
    deadline = time.monotonic() + SERVICE_START_WAIT_S
    while time.monotonic() < deadline:
        if service.poll() is not None:
            raise DemoError(f"the service exited with status {service.returncode} while starting")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise DemoError(f"the service did not listen on port {port} within {SERVICE_START_WAIT_S}s")


@contextmanager
def running_service(rig: Rig):
    """Start `symbiont serve` on the demo port and stop it afterwards, whatever happens."""
    log_path = rig.home / "service.log"
    with log_path.open("wb") as log:
        service = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "symbiont.cli",
                "serve",
                "--port",
                str(DEMO_PORT),
                "--data-dir",
                str(rig.data),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=rig.environment,
        )
        try:
            wait_until_listening(DEMO_PORT, service)
            yield
        finally:
            service.terminate()
            service.wait(timeout=10)


def failing_pytest_output(rig: Rig, selector: str) -> str:
    """Really run `pytest -q -k selector` in the working copy; it must fail."""
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "-rN",
            "-k",
            selector,
            "-p",
            "no:cacheprovider",
        ],
        cwd=rig.work,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 1:
        raise DemoError(f"expected the {selector} test to fail, pytest exited {done.returncode}")
    return done.stdout


def hook_event(rig: Rig, command: str, output: str) -> dict[str, object]:
    """The JSON Claude Code sends the plugin hook when a shell command fails."""
    return {
        "session_id": "demo-session-2",
        "cwd": str(rig.work),
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": f"Exit code 1\n{output}",
    }


def note_from_hook(printed: str) -> str:
    """The note inside the hook's JSON reply; DemoError when the hook said nothing."""
    if not printed.strip():
        raise DemoError("the hook printed nothing: no note for the repeated failure")
    reply = json.loads(printed.strip().splitlines()[-1])
    return str(reply["hookSpecificOutput"]["additionalContext"])


def replay_repeat_failure(rig: Rig) -> str:
    """Run the second task's test for real, send its failure to the hook, return the note."""
    command = "pytest -q --tb=short -rN -k invoice"
    output = failing_pytest_output(rig, "invoice")
    say(f"  the agent runs `{command}` and it fails again:")
    error_line = next(line for line in output.splitlines() if "AssertionError" in line)
    say(f"    {error_line.strip()}")
    event = json.dumps(hook_event(rig, command, output))
    printed = symbiont(
        rig,
        "hook",
        "PostToolUseFailure",
        "--harness",
        "claude_code",
        "--port",
        str(DEMO_PORT),
        "--data-dir",
        str(rig.data),
        stdin=event,
    )
    return note_from_hook(printed)


def check_note_names_the_earlier_fix(note: str) -> None:
    """Fail the demo unless the note is the exact-repeat note about the earlier fix."""
    wanted = ("Last time", "AssertionError", "ledger/invoices.py", "currency_exponent", USER_WORDS)
    missing = [part for part in wanted if part not in note]
    if missing:
        raise DemoError(f"the note does not mention {missing}; it says: {note!r}")


def teach_from_the_recorded_session(rig: Rig) -> None:
    """The user's side: say yes for this repository, then learn from its past sessions."""
    say("1. You switch symbiont on for this repository and let it learn from past sessions:")
    say(f"     $ symbiont repo allow    (project: {PROJECT})")
    allowed = symbiont(rig, "repo", "allow", "--project", PROJECT, "--data-dir", str(rig.data))
    say(f"     {allowed.strip()}")
    mined = symbiont(
        rig,
        "repo",
        "mine",
        "--project",
        PROJECT,
        "--repo-dir",
        str(rig.work),
        "--data-dir",
        str(rig.data),
        "--port",
        str(DEMO_PORT),
        "--no-open",
    )
    say(f"     $ symbiont repo mine\n     {mined.strip()}")
    lessons = symbiont(rig, "lessons", "--project", PROJECT, "--data-dir", str(rig.data))
    say("     $ symbiont lessons")
    for line in lessons.strip().splitlines():
        say(f"     {line}")
    words = (
        "Amounts are integers in each currency's minor units (JPY has none, BHD and KWD have "
        "three); never multiply by 100."
    )
    say(f'     $ symbiont context add last "{words}"')
    saved = symbiont(
        rig, "context", "add", "last", words, "--project", PROJECT, "--data-dir", str(rig.data)
    )
    say(f"     {saved.strip()}")


def demo(rig: Rig) -> None:
    """The whole story, narrated; raises DemoError when any step does not behave."""
    started = time.monotonic()
    say("symbiont, designed demo (synthetic repository, recorded session, no model, no network)")
    say()
    lay_out(rig)
    with running_service(rig):
        teach_from_the_recorded_session(rig)
        say()
        say("2. A new session on a fresh checkout; the same invoice test fails the same way:")
        note = replay_repeat_failure(rig)
        check_note_names_the_earlier_fix(note)
        say()
        say("3. What the agent is shown by the PostToolUseFailure hook:")
        say(f"     {note}")
        say()
        say("4. Ask why it spoke:")
        why = symbiont(rig, "why", "--project", PROJECT, "--data-dir", str(rig.data))
        for line in why.strip().splitlines():
            say(f"     {line}")
    say()
    seconds = time.monotonic() - started
    say(f"PASS: the repeat failure got a note about the earlier fix ({seconds:.1f}s)")


def main() -> int:
    """Build the rig under a temp directory, run the demo, always clean up."""
    top = Path(tempfile.mkdtemp(prefix="symbiont-demo-"))
    rig = Rig(home=top / "home", work=top / "work" / PROJECT, data=top / "data")
    rig.home.mkdir(parents=True)
    try:
        demo(rig)
    except DemoError as failed:
        sys.stderr.write(f"FAIL: {failed}\n")
        return 1
    finally:
        shutil.rmtree(top, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
