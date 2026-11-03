"""Reaching the local service from a hook, starting it when nothing is listening.

The first hook that finds the port empty starts `symbiont serve` (detached, log in the data
directory) and waits briefly; if it is still unreachable the hook says "symbiont offline" and
where the log is. A start is claimed in a marker file, so a service that cannot start is not
spawned again on every tool call.
"""

import subprocess
import time
from pathlib import Path

from symbiont.delivery.detached import spawn_detached
from symbiont.delivery.hooks import ServiceCall
from symbiont.delivery.recall import ServiceOfflineError, ServiceUnreachableError, call_service
from symbiont.egress.policy import LOCAL_SERVICE_PORT

DEFAULT_DATA_DIR = Path.home() / ".symbiont"
# Hook latency budget: a reachable service answers well inside this; the harness timeout is 2 s.
HOOK_TIMEOUT_S = 0.6
START_WAIT_S = 0.9
# A developer running a command can wait for a cold start (numpy and the readers import first).
PATIENT_WAIT_S = 15.0
POLL_S = 0.05
# A service that was started and still is not answering is not started again for this long.
RETRY_AFTER_S = 30.0
SERVICE_LOG = "service.log"
STARTING_MARK = "service.starting"


def reviving_call(data_dir: Path, port: int = LOCAL_SERVICE_PORT) -> ServiceCall:
    """A `ServiceCall` that starts the service once when nothing is listening, then retries."""

    def call(route: str, body: dict[str, object], at: int) -> dict[str, object]:
        """Call the service; on a down one, start it and wait up to START_WAIT_S."""
        try:
            return call_service(route, body, at, HOOK_TIMEOUT_S)
        except ServiceUnreachableError as down:
            if not _claim_start(data_dir):
                raise ServiceOfflineError(f"{down}; see {data_dir / SERVICE_LOG}") from down
            start_service(data_dir, at)
            return _after_start(route, body, at, data_dir)

    return call


def patient_call(data_dir: Path, wait_s: float = PATIENT_WAIT_S) -> ServiceCall:
    """A `ServiceCall` for a command a developer is waiting on: it starts a down service and waits.

    A hook may not wait for a cold start; `symbiont repo mine` can, because opening the dashboard
    needs the service that owns the mining job. Raises ServiceOfflineError after `wait_s`.
    """

    def call(route: str, body: dict[str, object], at: int) -> dict[str, object]:
        """Call the service; on a down one, start it once and wait for it."""
        try:
            return call_service(route, body, at)
        except ServiceUnreachableError:
            start_service(data_dir, at)
            return _after_start(route, body, at, data_dir, wait_s)

    return call


def start_service(data_dir: Path, port: int) -> None:
    """Run `symbiont serve` detached, appending its output to the data directory's log.

    Raises ServiceOfflineError, naming the fix, when the `symbiont` command cannot be run.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        with (data_dir / SERVICE_LOG).open("ab") as log:
            spawn_detached(
                lambda **detach: subprocess.Popen(
                    ["symbiont", "serve", "--port", str(port), "--data-dir", str(data_dir)],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    **detach,
                )
            )
    except OSError as failed:
        raise ServiceOfflineError(f"could not start the local service: {failed}") from failed


def _after_start(
    route: str, body: dict[str, object], port: int, data_dir: Path, wait_s: float = START_WAIT_S
) -> dict[str, object]:
    """Poll until the freshly started service answers, or raise ServiceOfflineError."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            return call_service(route, body, port, HOOK_TIMEOUT_S)
        except ServiceUnreachableError:
            time.sleep(POLL_S)
    raise ServiceOfflineError(
        f"the local service is still starting; its log is {data_dir / SERVICE_LOG}"
    )


def _claim_start(data_dir: Path) -> bool:
    """True for the one caller that may start the service now; others wait out RETRY_AFTER_S."""
    mark = data_dir / STARTING_MARK
    if mark.exists() and time.time() - mark.stat().st_mtime < RETRY_AFTER_S:
        return False
    data_dir.mkdir(parents=True, exist_ok=True)
    mark.touch()
    return True
