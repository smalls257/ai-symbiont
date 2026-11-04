"""A live judge demo: a real Muse Code session on the synthetic ledger, with symbiont installed.

Every setup step raises with the failing command's output, so a missing key or a plugin that did
not activate never leaves the judge in a session where symbiont silently says nothing. The history
is the hand-written one the keyless demo mines (no real transcripts); no nightly or Llama training.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import keyless_demo as keyless  # noqa: E402
import ledger_session as session  # noqa: E402

SERVICE_PORT = 7377
LAUNCHER_URL = "https://api.meta.ai/muse-launcher.sh"
# Muse is fetched when the container starts, not at image build: the key is only known at
# `docker run`, no auth state belongs in an image layer, and a stale layer would pin an old build.
MUSE_PATH = Path("/usr/local/bin/muse")
MARKETPLACE = "ai-symbiont"
PLUGIN = "symbiont"
REPO_ROOT = HERE.parents[1]
# Muse's own sandbox (bubblewrap) cannot make user namespaces under Docker's default seccomp
# profile and leaves the agent without a shell; Docker isolates the session instead. Approval
# prompts stay on. Our own synthetic repository is trusted, which spares the judge a prompt.
MUSE_ARGS = ("--disable-sandbox", "--trust-workspace")
STEP_TIMEOUT_S = 180.0
NO_KEY = (
    "META_API_KEY is not set. The live demo talks to Muse Code and needs your Meta API key:\n"
    "  docker run -it --rm -e META_API_KEY=... ai-symbiont live\n"
    "For a demo without a key: docker run --rm ai-symbiont demo"
)
CARD = f"""
== Try this (symbiont's notes appear as "symbiont:" lines in Muse)
  1. A task where house rules matter. Ask Muse:
       Add a function in ledger/ledger.py that books a refund for an invoice and returns the entry.
     symbiont should remind the agent of the two house rules the developer taught it:
       - {session.CORRECTIONS[0]}
       - {session.CORRECTIONS[1]}
  2. A repeated failure. Ask Muse:
       Run `{session.FAILING_TEST}` and fix the failure.
     The same command failed before; symbiont recalls what fixed it last time.
  3. Type /symbiont for status, or ask "why did you just warn me?" to hear why a note fired.
Skipped here: the nightly learner and Llama training (too slow on a CPU). Type /exit to leave.
"""


def say(text: str) -> None:
    """Print one narration line."""
    print(text, flush=True)


def require_key(environ: dict[str, str]) -> str:
    """The Meta API key; raise with the command to run when it is absent.

    Raises:
        SystemExit: no META_API_KEY in the environment.
    """
    key = environ.get("META_API_KEY", "").strip()
    if not key:
        raise SystemExit(NO_KEY)
    return key


def require_container(environ: dict[str, str]) -> None:
    """Refuse to run outside the image: the demo writes /usr/local/bin and ~/.symbiont, port 7377.

    Raises:
        SystemExit: SYMBIONT_DEMO_IN_DOCKER is unset, so this is probably a developer machine.
    """
    if not environ.get("SYMBIONT_DEMO_IN_DOCKER"):
        raise SystemExit(
            "The live demo is for the Docker image:\n"
            "  docker run -it --rm -e META_API_KEY=... ai-symbiont live"
        )


def run_step(label: str, argv: Sequence[str], *, cwd: Path, env: dict[str, str]) -> str:
    """Run one setup command, print its label, and return stdout; raise naming the failure.

    Raises:
        SystemExit: the command failed or timed out; the message carries its output, never env.
    """
    say(f"  - {label}")
    try:
        done = subprocess.run(
            list(argv), cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=STEP_TIMEOUT_S, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as late:
        raise SystemExit(
            f"{label}: timed out after {STEP_TIMEOUT_S:.0f}s ({late.cmd[0]})"
        ) from late
    if done.returncode != 0:
        raise SystemExit(f"{label} failed ({done.returncode}):\n{done.stdout}{done.stderr}")
    return done.stdout


def install_muse(desk: keyless.Desk) -> None:
    """Fetch Meta's launcher and let it download the current Muse Code build for this CPU."""
    launcher = run_step(
        "fetching the Muse launcher", ["curl", "-fsSL", LAUNCHER_URL], **where(desk)
    )
    MUSE_PATH.write_text(launcher, encoding="utf-8")
    MUSE_PATH.chmod(0o755)
    version = run_step("downloading Muse Code", [str(MUSE_PATH), "--version"], **where(desk))
    say(f"    {version.strip()}")


def where(desk: keyless.Desk) -> dict:
    """The working directory and environment of a setup command: the demo repository."""
    return {"cwd": desk.repo, "env": desk.env}


def install_plugin(desk: keyless.Desk) -> None:
    """Install and approve the symbiont plugin from this checkout's own marketplace."""
    muse = str(MUSE_PATH)
    steps = (
        ("adding the symbiont marketplace", ["plugins", "marketplace", "add", MARKETPLACE]),
        ("installing the symbiont plugin", ["plugins", "install", f"{PLUGIN}@{MARKETPLACE}"]),
        ("approving its hooks", ["plugins", "approve", PLUGIN]),
    )
    for label, argv in steps:
        extra = [str(REPO_ROOT)] if "marketplace" in argv else []
        run_step(label, [muse, *argv, *extra], **where(desk))


def teach_symbiont(desk: keyless.Desk) -> None:
    """Allow the repository, mine its hand-written history and save the two house rules."""
    for argv in (["repo", "allow"], ["repo", "mine"]):
        flags = ["--port", str(desk.port), "--repo-dir", str(desk.repo), "--no-open"]
        run_step(f"symbiont {' '.join(argv)}", ["symbiont", *argv, *flags], **where(desk))
    keyless.save_corrections(desk)


def build_desk(root: Path) -> keyless.Desk:
    """The demo repository with its history under the container's real HOME and default port.

    The desk's environment omits the API key: only Muse, started last, receives it.
    """
    repo = keyless.make_ledger_repo(root)
    home = Path(os.environ.get("HOME", "/root"))
    session.install_session(home, repo)
    keyless_env = {k: v for k, v in os.environ.items() if k != "META_API_KEY"}
    return keyless.Desk(repo, home / ".symbiont", SERVICE_PORT, keyless_env)


def main() -> int:
    """Set the demo up, print the card and hand the terminal to Muse; return Muse's exit code."""
    require_key(os.environ)
    require_container(os.environ)
    if not shutil.which("curl"):
        raise SystemExit("curl is missing from the image; rebuild it with `docker build`.")
    with tempfile.TemporaryDirectory(prefix="symbiont-live-") as name:
        desk = build_desk(Path(name))
        say("symbiont live demo: setting up (about a minute).")
        install_muse(desk)
        install_plugin(desk)
        with keyless.running_service(desk):
            teach_symbiont(desk)
            say(CARD)
            return subprocess.call(
                [str(MUSE_PATH), *MUSE_ARGS], cwd=desk.repo, env=dict(os.environ)
            )


if __name__ == "__main__":
    sys.exit(main())
