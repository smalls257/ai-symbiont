"""How to start a child process that outlives its parent, per operating system.

Why one function: a hook is killed with its process group when the harness times it out, and the
local service or a browser must survive that. POSIX does it with a new session; Windows has no
sessions, so it takes creation flags instead. Passing the POSIX option on Windows raises, which
would turn "start the service" into a silent "symbiont offline" on every Windows machine.
"""

import sys
from typing import Any

# Win32 process-creation flags (CreateProcess docs); `subprocess` only defines them on Windows.
# DETACHED_PROCESS: no console shared with the hook. CREATE_NEW_PROCESS_GROUP: the harness's
# Ctrl+C or group kill does not reach the child.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def detached_spawn_options(platform: str | None = None) -> dict[str, Any]:
    """The `subprocess.Popen` keywords that detach a child on `platform` (default: this one)."""
    if (platform or sys.platform) == "win32":
        return {"creationflags": _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}
