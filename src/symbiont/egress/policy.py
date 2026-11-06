"""What may leave this machine, decided without touching a network.

A private record (`remote_safe=False`) bound for a remote model raises, never filtered quietly or
sent with unknown provenance. The policy is a pure function over (endpoint, url, provenance); the
thin client in `client.py` owns the socket.
"""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit

from symbiont.egress.credentials import ApiKey
from symbiont.egress.providers import PROVIDERS
from symbiont.records.schema import Provenance

# Datasets whose rows are real people's text. remote_safe=False already covers them; the name
# check is a second lock for a record whose flag was set wrongly by a new reader.
PRIVATE_DATASETS = frozenset({"swe-chat", "swechat"})
LAN_SUFFIXES = (".local", ".lan", ".home", ".internal", ".localdomain", ".fritz.box")
# The only hosts a remote tier may reach, derived from the provider table (a code constant, never
# read from settings or the environment). Provenance says WHAT may leave; this says WHERE. A new
# model API is a new PROVIDERS entry and a policy test. Local tiers are bounded by loopback/LAN.
REMOTE_HOSTS = frozenset(entry.host for entry in PROVIDERS.values())
# 7377 spells SYMB on a phone keypad. Where the service listens and where its clients look is one
# fact, so it lives here, below both (a client must not import the service to learn it).
LOCAL_SERVICE_PORT = 7377


class Endpoint(StrEnum):
    """Which kind of server a payload is bound for; the kind decides what may go."""

    LOCAL_GLIMMER = "local_glimmer"  # the owner's own llama.cpp server (loopback or LAN)
    LOCAL_SERVICE = "local_service"  # the symbiont service on loopback
    LOCAL_MEMORY_MODEL = "local_memory_model"  # Route A's memory model (mlx_lm.server), loopback
    REMOTE_CHAT = "remote_chat"
    CONTRIBUTOR = "contributor"
    WONDER = "wonder"


REMOTE = frozenset({Endpoint.REMOTE_CHAT, Endpoint.CONTRIBUTOR, Endpoint.WONDER})


class EgressRefusedError(PermissionError):
    """Raised before any byte is sent; the message names the endpoint and the reason, never text."""


def _is_loopback(host: str) -> bool:
    """True for localhost and loopback addresses."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_lan(host: str) -> bool:
    """True for loopback and private LAN addresses."""
    if _is_loopback(host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host.endswith(LAN_SUFFIXES)
    return address.is_private or address.is_link_local


def _refuse_unless(endpoint: Endpoint, reason: str, *, holds: bool) -> None:
    """Raise EgressRefusedError naming the endpoint and reason unless `holds`."""
    if not holds:
        raise EgressRefusedError(f"egress to {endpoint.value} refused: {reason}")


@dataclass(frozen=True)
class Destination:
    """A server kind, the url to reach it and its credential; one object so callers cannot mix them.

    The key is optional (local servers take none) and never appears in the repr.
    """

    endpoint: Endpoint
    url: str
    api_key: ApiKey | None = field(default=None, repr=False)


def _check_destination(destination: Destination) -> None:
    """Refuse a url the endpoint may not reach."""
    endpoint, parts = destination.endpoint, urlsplit(destination.url)
    host = (parts.hostname or "").lower().rstrip(".")
    is_http = parts.scheme in ("http", "https") and bool(host)
    _refuse_unless(endpoint, "not an http(s) url with a host", holds=is_http)
    if endpoint is Endpoint.LOCAL_SERVICE:
        _refuse_unless(endpoint, "the local service is loopback only", holds=_is_loopback(host))
    elif endpoint is Endpoint.LOCAL_MEMORY_MODEL:
        # The memory model reads private session steps, so it may not sit even on the LAN.
        _refuse_unless(endpoint, "the memory model is loopback only", holds=_is_loopback(host))
    elif endpoint is Endpoint.LOCAL_GLIMMER:
        _refuse_unless(endpoint, "a Glimmer host must be loopback or LAN", holds=_is_lan(host))
    else:
        _refuse_unless(endpoint, "remote model endpoints need https", holds=parts.scheme == "https")
        _refuse_unless(
            endpoint, "a remote endpoint cannot be a private host", holds=not _is_lan(host)
        )
        _refuse_unless(
            endpoint, f"host {host!r} is not an allowed remote host", holds=host in REMOTE_HOSTS
        )


def _check_provenance(endpoint: Endpoint, provenance: Iterable[Provenance]) -> None:
    """Refuse payloads with no provenance or provenance the endpoint may not carry."""
    declared = list(provenance)
    no_provenance = "no provenance declared (unknown privacy is never shareable)"
    _refuse_unless(endpoint, no_provenance, holds=bool(declared))
    for item in declared:
        name = repr(item.dataset)
        _refuse_unless(
            endpoint, f"a record from {name} is remote_safe=False", holds=item.remote_safe
        )
        _refuse_unless(
            endpoint, f"{name} is private", holds=item.dataset.lower() not in PRIVATE_DATASETS
        )


def check_outbound(destination: Destination, provenance: Iterable[Provenance] = ()) -> None:
    """Raise `EgressRefusedError` unless this payload may go there; local endpoints take any."""
    _check_destination(destination)
    if destination.endpoint in REMOTE:
        _check_provenance(destination.endpoint, provenance)
