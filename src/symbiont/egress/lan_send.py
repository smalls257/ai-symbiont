"""The LAN door: research runs reach the owner's Glimmer server here, never the published package.

Glimmer (a llama.cpp server for Act 1 and the gate experiments) may sit on loopback or on the
home LAN; the published package reaches loopback only, so this module is excluded from the wheel
(pyproject `wheel-exclude`). No provenance is declared: Glimmer is the owner's own machine, and a
public host is refused before any byte is sent.
"""

import ipaddress
import json
import logging
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from symbiont.egress.client import Transport, open_without_redirects
from symbiont.egress.policy import EgressRefusedError, host_of, is_loopback, refuse_unless

log = logging.getLogger("symbiont.egress")

LAN_SUFFIXES = (".local", ".lan", ".home", ".internal", ".localdomain", ".fritz.box")
GLIMMER = "local_glimmer"


def is_lan(host: str) -> bool:
    """True for loopback, private LAN addresses and bare or LAN-suffixed host names."""
    if is_loopback(host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host.endswith(LAN_SUFFIXES)
    return address.is_private or address.is_link_local


def check_glimmer(url: str) -> None:
    """Raise `EgressRefusedError` unless the url is http(s) on a loopback or LAN host."""
    host = host_of(url)
    is_http = urlsplit(url).scheme in ("http", "https") and bool(host)
    refuse_unless(GLIMMER, "not an http(s) url with a host", holds=is_http)
    refuse_unless(GLIMMER, "a Glimmer host must be loopback or LAN", holds=is_lan(host))


def post_glimmer_json(
    url: str,
    body: Mapping[str, object],
    *,
    timeout_s: float = 300.0,
    transport: Transport = open_without_redirects,
) -> dict[str, Any]:
    """POST `body` as JSON to a Glimmer server; raises `EgressRefusedError` before sending."""
    wire_bytes = json.dumps(body).encode()
    described = f"endpoint={GLIMMER} host={host_of(url)} bytes={len(wire_bytes)}"
    try:
        check_glimmer(url)
    except EgressRefusedError as refusal:
        log.warning("%s (%s)", refusal, described)
        raise
    log.info("egress send %s", described)
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=wire_bytes, headers=headers)
    reply: dict[str, Any] = json.loads(transport(request, timeout_s))
    return reply
