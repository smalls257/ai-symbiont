"""The dashboard's views and the one place their address is spelled.

The CLI, the hooks and the MCP tool share this one spelling, so a new view is one edit.
"""

from enum import StrEnum


class DashboardView(StrEnum):
    """A dashboard page the developer can open on demand; the value is the address's `view=`."""

    INBOX = "inbox"
    TOPICS = "topics"
    TRENDS = "trends"
    STRUGGLE = "struggle"
    CONTEXT = "context"
    REPLAY = "replay"


def dashboard_address(port: int, project: str, view: DashboardView | None) -> str:
    """The loopback address of `project`'s dashboard on `view` (None: the page's own default).

    The project is percent-encoded. `view=` rides last so a page that does not read it yet still
    loads: extra query parameters are ignored.
    """
    safe = "".join(
        char
        if char.isascii() and (char.isalnum() or char in "-._~")
        else "".join(f"%{b:02X}" for b in char.encode())
        for char in project
    )
    address = f"http://127.0.0.1:{port}/dashboard?project={safe}"
    return address if view is None else f"{address}&view={view.value}"
