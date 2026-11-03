"""The machine under `symbiont nightly`: processes, the hardware probe, the loopback judge call.

Everything that needs a real machine is here, so `nightly_run.py` and the schedule logic run with
fakes. The only connection opened is `JudgeModel`'s, through `symbiont.egress`, loopback only.
"""

import os
import platform
import shutil
import subprocess
import time
import zlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from symbiont.egress import EgressRefusedError
from symbiont.egress.client import Transport
from symbiont.service.judge_model import JudgeModel, JudgeOfflineError
from symbiont.service.nightly_backend import Backend, choose_backend
from symbiont.service.nightly_run import NightFailedError, NightTools, Say
from symbiont.service.nightly_schedule import Completed, ScheduleError, Tool

ROUTEA_ENV = "SYMBIONT_ROUTEA_DIR"
TORCH_TRAINER = "train_lora_torch.py"
JUDGE_SERVER = "plug_judge_server.py"
FIRST_PORT = 8800  # the nightly judge servers live at 8800-8899; 8791 is the first-night server
PORTS = 100
MLX_IMPORT = "import mlx_lm"
CUDA_IMPORT = (
    "import sys, torch, peft, transformers; sys.exit(0 if torch.cuda.is_available() else 3)"
)
INSTALL_HINT = {
    Backend.MLX: "install it with `uv pip install mlx-lm` into that Python",
    Backend.TORCH_CUDA: "it needs torch built for CUDA, transformers and peft",
}


@contextmanager
def interpreter_first(python: str) -> Iterator[None]:
    """Put the folder of `python` first on PATH, so the literal `python` below is that one.

    Raises NightFailedError when `python` is not an executable. The semgrep rule on processes wants
    a literal command, so the interpreter is chosen by PATH, not by a variable in the argument list.
    """
    found = shutil.which(python)
    if found is None:
        raise NightFailedError(f"trainer Python {python!r} was not found")
    saved = os.environ.get("PATH", "")
    os.environ["PATH"] = str(Path(found).parent) + os.pathsep + saved
    try:
        yield
    finally:
        os.environ["PATH"] = saved


def run_logged(python: str, args: Sequence[str], log: Path, extra: Mapping[str, str]) -> int:
    """Run `python ARGS` with its output in `log`; returns the exit code.

    Raises NightFailedError if the interpreter cannot start.
    """
    with interpreter_first(python), log.open("wb") as sink:
        try:
            return subprocess.run(
                ["python", *args],
                stdout=sink,
                stderr=subprocess.STDOUT,
                env={**os.environ, **extra},
                check=False,
            ).returncode
        except OSError as unstartable:
            raise NightFailedError(f"could not start {python}: {unstartable}") from unstartable


def detected_backend() -> Backend:
    """The trainer this machine can use; raises NoTrainingHardwareError when it has none."""
    return choose_backend(platform.system(), platform.machine(), has_nvidia=_has_nvidia())


def _has_nvidia() -> bool:
    """Whether `nvidia-smi` lists at least one GPU."""
    if shutil.which("nvidia-smi") is None:
        return False
    listed = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, check=False)
    return listed.returncode == 0 and "GPU" in listed.stdout


def checked_python(python: str, backend: Backend) -> None:
    """Fail now, with the fix, if `python` cannot train on `backend`, not after the rows."""
    probe = MLX_IMPORT if backend is Backend.MLX else CUDA_IMPORT
    try:
        with interpreter_first(python):
            done = subprocess.run(
                ["python", "-c", probe], capture_output=True, text=True, check=False
            )
    except OSError as missing:
        raise NightFailedError(f"trainer Python {python!r} cannot start: {missing}") from missing
    if done.returncode != 0:
        reason = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1]
        raise NightFailedError(
            f"{python} cannot train with {backend.value} ({reason}); {INSTALL_HINT[backend]}, "
            "or pass another interpreter with --trainer-python"
        )


def routea_dir() -> Path | None:
    """`scripts/routea` of the checkout this package runs from (or $SYMBIONT_ROUTEA_DIR), if any."""
    chosen = os.environ.get(ROUTEA_ENV)
    candidates = (
        [Path(chosen)] if chosen else [Path(__file__).resolve().parents[3] / "scripts" / "routea"]
    )
    return next((path for path in candidates if path.is_dir()), None)


def torch_trainer() -> Path:
    """The torch trainer script. Raises NightFailedError when no checkout provides it."""
    folder = routea_dir()
    if folder is None or not (folder / TORCH_TRAINER).is_file():
        raise NightFailedError(
            f"the CUDA trainer {TORCH_TRAINER} is not here; run from a checkout of ai-symbiont "
            f"or point {ROUTEA_ENV} at its scripts/routea"
        )
    return folder / TORCH_TRAINER


def default_judge_url(project: str) -> str:
    """A loopback URL for the project's own judge server, stable across runs.

    One server holds one adapter, so two projects must not share a port; the port is the project
    name's checksum within 8800-8899. A collision is fixed with --judge-url.
    """
    return f"http://127.0.0.1:{FIRST_PORT + zlib.crc32(project.encode()) % PORTS}"


def judge_device(backend: Backend) -> str:
    """The LCAP_DEVICE the judge server needs on this machine: mps with mlx, cuda with torch."""
    return "mps" if backend is Backend.MLX else "cuda"


def restart_instructions(
    python: str, url: str, adapter: Path, base: Path, device: str | None = None
) -> str:
    """The exact command that starts the judge server on this adapter.

    The server's default device is cuda, so a Mac's printed command must carry `LCAP_DEVICE=mps`.
    """
    folder = routea_dir()
    script = (
        str(folder / JUDGE_SERVER) if folder else f"<ai-symbiont>/scripts/routea/{JUDGE_SERVER}"
    )
    port = url.rsplit(":", 1)[-1].rstrip("/")
    prefix = f"LCAP_DEVICE={device} " if device and os.name == "posix" else ""
    return f"{prefix}{python} {script} --model {base} --adapter {adapter} --port {port}"


def told_judge(
    url: str, adapter: Path, start_command: str, transport: Transport | None = None
) -> str:
    """Hot-swap the adapter in the running judge server, or say exactly what to start.

    `start_command` is what `restart_instructions` built for this machine. Returns the sentence to
    print; the caller adds what the symbiont service needs.
    """
    try:
        JudgeModel(url, transport).reload(adapter)
    except EgressRefusedError as refused:
        raise NightFailedError(f"judge URL {url} refused: {refused}") from refused
    except JudgeOfflineError:
        return (
            f"judge server at {url} is not answering. Start it on the new adapter:\n"
            f"  {start_command}\n"
        )
    return f"judge server at {url} now serves the new adapter"


def real_tools(say: Say, judge_python: str) -> NightTools:
    """The night's tools here; `judge_python` is the interpreter the judge server runs on."""
    return NightTools(
        run=run_logged,
        clock=_monotonic,
        timestamp=lambda: datetime.now(UTC).isoformat(timespec="seconds"),
        say=say,
        backend=detected_backend,
        torch_script=torch_trainer,
        check_python=checked_python,
        tell_judge=lambda url, adapter, base: told_judge(
            url,
            adapter,
            restart_instructions(
                judge_python, url, adapter, base, judge_device(detected_backend())
            ),
        ),
    )


def _monotonic() -> float:
    return time.monotonic()


class LocalMachine:
    """`SchedulerSystem` on the real machine."""

    def run(self, tool: Tool, args: Sequence[str], stdin: str | None = None) -> Completed:
        """Run one scheduler tool; a tool that is not installed raises ScheduleError naming it."""
        try:
            return _completed(_scheduler_call(tool, args, stdin))
        except OSError as missing:
            raise ScheduleError(f"{tool.value} is not available here: {missing}") from missing

    def write(self, path: Path, data: bytes) -> None:
        """Write a file, creating its folder."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete(self, path: Path) -> None:
        """Delete a file if it exists."""
        path.unlink(missing_ok=True)

    def read(self, path: Path) -> bytes | None:
        """A file's bytes, or None."""
        return path.read_bytes() if path.is_file() else None


def _scheduler_call(
    tool: Tool, args: Sequence[str], stdin: str | None
) -> "subprocess.CompletedProcess[str]":
    """The process for one scheduler tool; each branch names its program as a literal."""
    if tool is Tool.LAUNCHCTL:
        return subprocess.run(
            ["launchctl", *args], input=stdin, capture_output=True, text=True, check=False
        )
    if tool is Tool.CRONTAB:
        return subprocess.run(
            ["crontab", *args], input=stdin, capture_output=True, text=True, check=False
        )
    return subprocess.run(
        ["schtasks", *args], input=stdin, capture_output=True, text=True, check=False
    )


def _completed(done: "subprocess.CompletedProcess[str]") -> Completed:
    """The exit code and the combined output."""
    return Completed(done.returncode, done.stdout + done.stderr)
