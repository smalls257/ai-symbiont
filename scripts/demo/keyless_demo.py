"""A keyless, offline replay of the symbiont product flow, narrated like a terminal session.

It builds a synthetic ledger repository and a hand-written agent session for it, starts the real
`symbiont serve` on a temp data dir and a free loopback port with HOME isolated, and drives the
real commands and hook events against it. No API key, no model call, no network beyond loopback.
Every note printed here comes out of the service the harness hooks talk to, never from a mock
that could show a note the product would not say.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ledger_session as session  # noqa: E402

from symbiont.delivery.recall import call_service  # noqa: E402
from symbiont.store.settings import write_mining_setting  # noqa: E402

LEDGER = HERE.parents[1] / "examples" / "ledger"
PROJECT = "ledger"
CORRECTION_LABEL = "from correction"
START_TIMEOUT_S = 30.0
STEP_TIMEOUT_S = 60.0
CLI = "import sys; from symbiont.cli import main; sys.exit(main())"


@dataclass(frozen=True)
class Desk:
    """Where the demo lives: the repository, the isolated data and HOME, and the service port."""

    repo: Path
    data: Path
    port: int
    env: dict[str, str]


def say(text: str = "") -> None:
    """Print one narration line."""
    print(text, flush=True)


def step(number: int, title: str) -> None:
    """Print a step heading."""
    say(f"\n== Step {number}: {title}")


def free_port() -> int:
    """A loopback port nothing listens on; never the owner's own service port."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def isolated_env(root: Path) -> dict[str, str]:
    """The environment of every child: HOME inside the temp dir, and no API key."""
    env = {k: v for k, v in os.environ.items() if k != "META_API_KEY"}
    home = root / "home"
    home.mkdir(exist_ok=True)
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_DATA_HOME=str(root / "xdg"))
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return env


def make_ledger_repo(root: Path) -> Path:
    """A git repository holding a copy of the synthetic billing ledger."""
    repo = root / PROJECT
    shutil.copytree(LEDGER, repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    git = ["git", "-c", "user.name=demo", "-c", "user.email=demo", "-C", str(repo)]
    for argument in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "synthetic ledger"]):
        subprocess.run([*git, *argument], check=True, capture_output=True)
    return repo


def symbiont(desk: Desk, *argv: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run the real `symbiont` command in the repository with the isolated environment."""
    return subprocess.run(
        [sys.executable, "-c", CLI, *argv],
        cwd=desk.repo,
        env=desk.env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=STEP_TIMEOUT_S,
        check=False,
    )


def show_command(argv: list[str]) -> None:
    """Print the command as a developer would type it."""
    say("$ " + " ".join(argv))


def run_visible(desk: Desk, *argv: str) -> str:
    """Run a command, print it and its output, and return the output; a failure stops the demo.

    The printed command is what a developer types; the temp paths and port the demo adds are not.
    """
    show_command(["symbiont", *argv])
    done = symbiont(desk, *argv, *plumbing(desk, argv[0]))
    if done.returncode != 0:
        raise SystemExit(f"symbiont {argv[0]} failed:\n{done.stdout}{done.stderr}")
    say(done.stdout.strip())
    return done.stdout


def plumbing(desk: Desk, command: str) -> list[str]:
    """The isolation flags the demo appends to a command (a real run uses the defaults)."""
    flags = ["--data-dir", str(desk.data)]
    if command == "repo":
        flags += ["--port", str(desk.port), "--repo-dir", str(desk.repo), "--no-open"]
    return flags


def hook_note(desk: Desk, event: str, payload: dict) -> str:
    """Pipe one hook event into `symbiont hook` and return the context the model would see."""
    body = {"session_id": "demo-live", "cwd": str(desk.repo), **payload}
    show_command(["echo", f"'<{event} event>'", "|", "symbiont", "hook", event])
    argv = ["hook", event, "--harness", "claude_code", "--port", str(desk.port)]
    done = symbiont(desk, *argv, "--data-dir", str(desk.data), stdin=json.dumps(body))
    if done.returncode != 0 or not done.stdout.strip():
        raise SystemExit(f"the {event} hook said nothing:\n{done.stderr}")
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]


def quote_note(text: str) -> None:
    """Print a note the way the model receives it."""
    for line in text.splitlines():
        say(f"  | {line}")


@contextmanager
def running_service(desk: Desk) -> Iterator[None]:
    """Run `symbiont serve` on the desk's port until the block ends."""
    argv = [sys.executable, "-c", CLI, "serve", "--port", str(desk.port)]
    argv += ["--data-dir", str(desk.data)]
    service = subprocess.Popen(
        argv, cwd=desk.repo, env=desk.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        wait_until_listening(desk.port, service)
        yield
    finally:
        service.terminate()
        service.wait(timeout=STEP_TIMEOUT_S)


def wait_until_listening(port: int, service: subprocess.Popen) -> None:
    """Block until the service accepts a connection; raise when it died or never came up."""
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if service.poll() is not None:
            raise SystemExit(f"symbiont serve exited with code {service.returncode}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"symbiont serve did not listen on port {port} within {START_TIMEOUT_S}s")


def save_corrections(desk: Desk) -> None:
    """Save the corrections through the service route the MCP tool `symbiont_add_lessons` uses."""
    lessons = [
        {"text_in_plain_words": text, "kind": "correction", "source_label": CORRECTION_LABEL}
        for text in session.CORRECTIONS
    ]
    show_command(["symbiont_add_lessons", *(f'"{text}"' for text in session.CORRECTIONS)])
    saved = call_service("/lessons/add", {"project": PROJECT, "lessons": lessons}, desk.port)
    say(f"saved {saved['added']} lessons, each labeled '{CORRECTION_LABEL}'")


def narrate_flow(desk: Desk) -> None:
    """The product flow, one step at a time."""
    step(1, "A new session starts in a repository symbiont has not been told about")
    quote_note(hook_note(desk, "SessionStart", {"source": "startup"}).split("\n", 1)[0])
    step(2, "The developer says yes")
    run_visible(desk, "repo", "allow")
    step(3, "Learn from the repository's past sessions")
    run_visible(desk, "repo", "mine")
    step(4, "The session's model curates the developer's corrections (no model runs in this demo)")
    save_corrections(desk)
    step(5, "The next session starts: the house rules come first")
    quote_note(hook_note(desk, "SessionStart", {"source": "startup"}).split("\n", 1)[0])
    step(6, "The same pytest command fails again: symbiont recalls what fixed it last time")
    failure = {"tool_name": "Bash", "tool_input": {"command": session.FAILING_TEST}}
    failure |= {"tool_response": None, "error": "Exit code 1\n" + session.FAILURE_TEXT}
    quote_note(hook_note(desk, "PostToolUseFailure", failure))
    step(7, "Ask why it spoke")
    run_visible(desk, "why")


def summary(desk: Desk) -> None:
    """End the walkthrough with what was shown and where the dashboard is."""
    say("\n== Summary")
    say("  - A hand-written session of a synthetic ledger was mined; no real transcript was used.")
    say("  - Two corrections became house rules, said first at session start.")
    say("  - A repeated pytest failure got a recall note naming the earlier fix.")
    say("  - No API key, no model call, no network beyond 127.0.0.1.")
    if os.environ.get("SYMBIONT_DEMO_IN_DOCKER"):
        say("  - In Docker the service is not reachable from the host; the dashboard is for local")
        say("    runs: `uv run python scripts/demo/keyless_demo.py`.")
    else:
        say(f"  - Dashboard (while the demo ran): http://127.0.0.1:{desk.port}/dashboard")


def main() -> int:
    """Build the desk, start the service and narrate the flow; return the exit code."""
    with tempfile.TemporaryDirectory(prefix="symbiont-demo-") as name:
        root = Path(name)
        env = isolated_env(root)
        repo = make_ledger_repo(root)
        session.install_session(Path(env["HOME"]), repo)
        desk = Desk(repo, root / "data", free_port(), env)
        # The demo's history is one hand-written session, so a trap is taught after one sighting.
        write_mining_setting(desk.data, "min_sessions", 1)
        say("symbiont keyless demo: a synthetic ledger repository, replayed, offline.")
        with running_service(desk):
            narrate_flow(desk)
        summary(desk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
