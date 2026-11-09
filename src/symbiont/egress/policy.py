"""What may leave this machine from the published package, decided without touching a network.

Every endpoint here is local: the symbiont service and the memory model on loopback, the owner's
Glimmer server on loopback or the LAN. No remote host exists in this module, so a shipped install
cannot reach one. Remote model calls are research code (`remote_send.py`), kept out of the wheel.
The policy is a pure function over (endpoint, url); the thin client in `client.py` owns the socket.
"""

import ipaddress
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

LAN_SUFFIXES = (".local", ".lan", ".home", ".internal", ".localdomain", ".fritz.box")
# 7377 spells SYMB on a phone keypad. Where the service listens and where its clients look is one
# fact, so it lives here, below both (a client must not import the service to learn it).
LOCAL_SERVICE_PORT = 7377


class Endpoint(StrEnum):
    """Which local server a payload is bound for; the kind decides which hosts it may reach."""

    LOCAL_GLIMMER = "local_glimmer"  # the owner's own llama.cpp server (loopback or LAN)
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


def is_lan(host: str) -> bool:
    """True for loopback, private LAN addresses and bare or LAN-suffixed host names."""
    if is_loopback(host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host.endswith(LAN_SUFFIXES)
    return address.is_private or address.is_link_local


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
    """Raise `EgressRefusedError` unless the url is http(s) on a host its endpoint may reach."""
    endpoint, host = destination.endpoint, host_of(destination.url)
    is_http = urlsplit(destination.url).scheme in ("http", "https") and bool(host)
    refuse_unless(endpoint.value, "not an http(s) url with a host", holds=is_http)
    if endpoint is Endpoint.LOCAL_GLIMMER:
        refuse_unless(endpoint.value, "a Glimmer host must be loopback or LAN", holds=is_lan(host))
        return
    # The service and the memory model read private session steps, so not even the LAN.
    refuse_unless(endpoint.value, "this endpoint is loopback only", holds=is_loopback(host))
