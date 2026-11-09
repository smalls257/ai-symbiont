"""What may leave this machine from the published package, decided without touching a network.

Every endpoint here is loopback: the symbiont service and the memory model. No LAN or remote host
is reachable from this module, so a shipped install talks to 127.0.0.1 and nothing else (plus the
Hugging Face download in `download.py`). The LAN door for Glimmer (`lan_send.py`) and the remote
model door (`remote_send.py`) are research code, kept out of the wheel.
The policy is a pure function over (endpoint, url); the thin client in `client.py` owns the socket.
"""

import ipaddress
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

# 7377 spells SYMB on a phone keypad. Where the service listens and where its clients look is one
# fact, so it lives here, below both (a client must not import the service to learn it).
LOCAL_SERVICE_PORT = 7377


class Endpoint(StrEnum):
    """Which loopback server a payload is bound for."""

    LOCAL_SERVICE = "local_service"  # the symbiont service on loopback
    LOCAL_MEMORY_MODEL = "local_memory_model"  # Route A's memory model (mlx_lm.server), loopback


class EgressRefusedError(PermissionError):
    """Raised before any byte is sent; the message names the endpoint and the reason, never text."""


def is_loopback(host: str) -> bool:
    """True for localhost and loopback addresses."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def host_of(url: str) -> str:
    """The url's host, lowercased and without a trailing dot; "" when it has none."""
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def refuse_unless(endpoint: str, reason: str, *, holds: bool) -> None:
    """Raise EgressRefusedError naming the endpoint and reason unless `holds`."""
    if not holds:
        raise EgressRefusedError(f"egress to {endpoint} refused: {reason}")


@dataclass(frozen=True)
class Destination:
    """A local server kind and the url to reach it; one object so callers cannot mix them."""

    endpoint: Endpoint
    url: str


def check_outbound(destination: Destination) -> None:
    """Raise `EgressRefusedError` unless the url is http(s) on a loopback host."""
    endpoint, host = destination.endpoint, host_of(destination.url)
    is_http = urlsplit(destination.url).scheme in ("http", "https") and bool(host)
    refuse_unless(endpoint.value, "not an http(s) url with a host", holds=is_http)
    # The service and the memory model read private session steps, so not even the LAN.
    refuse_unless(endpoint.value, "this endpoint is loopback only", holds=is_loopback(host))
