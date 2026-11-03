"""Opening an address in the developer's default browser: the delivery side of "show me".

Opening a window is a client concern, so the service never does it. A machine with no way to open
one (a server, a container) must be told so, because a silently unopened dashboard looks like a
dashboard that does not exist; the caller prints the address as well.
"""

import subprocess
import sys
from typing import Any

# Detached and silent: a slow browser start must never hold up mining, nor write on its terminal.
_DETACHED: dict[str, Any] = {
    "stdin": subprocess.DEVNULL,
    "stdout": subprocess.DEVNULL,
    "stderr": subprocess.DEVNULL,
    "start_new_session": True,
}


def open_in_browser(url: str) -> bool:
    """Ask the desktop to open `url`; False when it cannot, never an exception for a missing opener.

    Only a loopback dashboard address is ever passed here.
    """
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url], **_DETACHED)
        elif sys.platform == "linux":
            subprocess.Popen(["xdg-open", url], **_DETACHED)
        else:
            return False
    except OSError:
        return False
    return True
