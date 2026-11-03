"""How to start a child process that outlives its parent, per operating system.

Why one function: a hook is killed with its process group when the harness times it out, and the
local service or a browser must survive that. POSIX does it with a new session; Windows has no
sessions, so it takes creation flags instead. Passing the POSIX option on Windows raises, which
would turn "start the service" into a silent "symbiont offline" on every Windows machine.
"""

import errno
import logging
import sys
from collections.abc import Callable
from typing import Any

log = logging.getLogger("symbiont.detached")

# Win32 CreateProcess flags. Breakaway is the only one that leaves a job object (OpenSSH and some
# harnesses kill the whole job tree on close), and only if the job allows it.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_ERROR_ACCESS_DENIED = 5


def detached_spawn_options(platform: str | None = None) -> dict[str, Any]:
    """The `subprocess.Popen` keywords that detach a child on `platform` (default: this one)."""
    if (platform or sys.platform) == "win32":
        flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP | _CREATE_BREAKAWAY_FROM_JOB
        return {"creationflags": flags}
    return {"start_new_session": True}


def _is_breakaway_refused(failed: OSError) -> bool:
    """A job that forbids breakaway makes CreateProcess fail with access denied."""
    return getattr(failed, "winerror", None) == _ERROR_ACCESS_DENIED or failed.errno == errno.EACCES


def spawn_detached(start: Callable[..., object], platform: str | None = None) -> None:
    """Call `start(**options)` (a Popen with a literal command) with the detach options.

    If a Windows job forbids breakaway, retries once inside the job and warns loudly. Other
    OSErrors propagate: a missing executable is not a refused breakaway.
    """
    options = detached_spawn_options(platform)
    try:
        start(**options)
    except OSError as failed:
        if "creationflags" not in options or not _is_breakaway_refused(failed):
            raise
        log.warning(
            "the enclosing Windows job forbids breakaway (%s); the child was started inside it "
            "and may die with the session that started it",
            failed,
        )
        options["creationflags"] &= ~_CREATE_BREAKAWAY_FROM_JOB
        start(**options)
