"""Which Host and Origin the loopback service answers: the DNS-rebinding guard.

A page on an attacker's domain can be re-pointed at 127.0.0.1 and then read
`/dashboard/session` as same-origin; its requests still carry the attacker's name in `Host`
(and `Origin` on a POST), so refusing every name but ours closes that door in one place.
"""

import re

LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
_HOST = re.compile(r"^(?P<name>\[[0-9a-f:]+\]|[^:\[\]]+)(?::(?P<port>\d+))?$")


def refusal_reason(host: str | None, origin: str | None, method: str, port: int) -> str | None:
    """Why this request is refused, or None when it may be answered.

    `origin` is checked only on a POST, the one state-changing method; a client that sends none
    (the CLI, the hooks, MCP delivery) is not a browser page and passes.
    """
    if not _is_ours(host, port):
        return "unexpected Host header"
    if method == "POST" and origin is not None and not _origin_is_ours(origin, port):
        return "unexpected Origin header"
    return None


def _is_ours(host: str | None, port: int) -> bool:
    found = _HOST.match(host or "")
    return (
        bool(found)
        and found.group("name") in LOOPBACK_NAMES
        and found.group("port") in (None, str(port))
    )


def _origin_is_ours(origin: str, port: int) -> bool:
    scheme, separator, host = origin.partition("://")
    return separator == "://" and scheme == "http" and _is_ours(host, port)
