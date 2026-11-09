"""The remote door: research runs reach a remote model API here, never in the published package.

The wheel excludes this module (pyproject `wheel-exclude`), so an install has no path to a remote
host. A private record (`remote_safe=False`) bound for a remote model raises, never filtered
quietly or sent with unknown provenance; the host must be in the provider table (a code
constant, never read from settings or the environment). Provenance says WHAT may leave; the
table says WHERE.
"""

import json
import logging
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from symbiont.egress.client import Transport, open_without_redirects
from symbiont.egress.credentials import ApiKey
from symbiont.egress.policy import EgressRefusedError, host_of, is_lan, refuse_unless
from symbiont.egress.providers import PROVIDERS
from symbiont.records.schema import Provenance

log = logging.getLogger("symbiont.egress")

# Datasets whose rows are real people's text. remote_safe=False already covers them; the name
# check is a second lock for a record whose flag was set wrongly by a new reader.
PRIVATE_DATASETS = frozenset({"swe-chat", "swechat"})
REMOTE_HOSTS = frozenset(entry.host for entry in PROVIDERS.values())


class RemoteEndpoint(StrEnum):
    """Which remote tier a payload is bound for; every tier gets the same checks."""

    REMOTE_CHAT = "remote_chat"
    CONTRIBUTOR = "contributor"
    WONDER = "wonder"


@dataclass(frozen=True)
class RemoteDestination:
    """A remote tier, its url and its key; the key never appears in the repr."""

    endpoint: RemoteEndpoint
    url: str
    api_key: ApiKey | None = field(default=None, repr=False)


def check_remote(destination: RemoteDestination, provenance: Iterable[Provenance]) -> None:
    """Raise `EgressRefusedError` unless this payload may go to this remote host."""
    endpoint, host = destination.endpoint.value, host_of(destination.url)
    refuse_unless(endpoint, "not an http(s) url with a host", holds=bool(host))
    https = urlsplit(destination.url).scheme == "https"
    refuse_unless(endpoint, "remote model endpoints need https", holds=https)
    refuse_unless(endpoint, "a remote endpoint cannot be a private host", holds=not is_lan(host))
    allowed = host in REMOTE_HOSTS
    refuse_unless(endpoint, f"host {host!r} is not an allowed remote host", holds=allowed)
    _check_provenance(endpoint, list(provenance))


def _check_provenance(endpoint: str, declared: list[Provenance]) -> None:
    no_provenance = "no provenance declared (unknown privacy is never shareable)"
    refuse_unless(endpoint, no_provenance, holds=bool(declared))
    for item in declared:
        name = repr(item.dataset)
        unsafe = f"a record from {name} is remote_safe=False"
        refuse_unless(endpoint, unsafe, holds=item.remote_safe)
        private = item.dataset.lower() in PRIVATE_DATASETS
        refuse_unless(endpoint, f"{name} is private", holds=not private)


def post_remote_json(
    destination: RemoteDestination,
    body: Mapping[str, object],
    *,
    provenance: Iterable[Provenance],
    timeout_s: float = 300.0,
    transport: Transport = open_without_redirects,
) -> dict[str, Any]:
    """POST `body` as JSON with the bearer key; raises `EgressRefusedError` before sending."""
    declared = list(provenance)
    wire_bytes = json.dumps(body).encode()
    described = _describe(destination, len(wire_bytes), declared)
    try:
        check_remote(destination, declared)
    except EgressRefusedError as refusal:
        log.warning("%s (%s)", refusal, described)
        raise
    log.info("egress send %s", described)
    headers = {"Content-Type": "application/json"}
    if destination.api_key is not None:
        headers["Authorization"] = f"Bearer {destination.api_key.reveal()}"
    request = urllib.request.Request(destination.url, data=wire_bytes, headers=headers)
    reply: dict[str, Any] = json.loads(transport(request, timeout_s))
    return reply


def _describe(destination: RemoteDestination, size: int, provenance: list[Provenance]) -> str:
    """The log line for a send: endpoint, host, size and dataset names, never the payload."""
    datasets = sorted({p.dataset for p in provenance})
    return (
        f"endpoint={destination.endpoint.value} host={host_of(destination.url)} "
        f"bytes={size} records={len(provenance)} datasets={datasets or 'none'}"
    )
