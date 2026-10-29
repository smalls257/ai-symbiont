"""The thin client: policy first, then one POST, logging sizes and provenance only.

Violation this shape prevents: Black Box on the way out (nobody can tell what left the machine)
and Silent Fallback (a refused or failed send must raise, never return an empty reply).
The prompt text is never logged. The only module in src/ allowed to open a connection
(semgrep sym-single-egress).
"""

import json
import logging
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from symbiont.egress.policy import Destination, EgressRefusedError, check_outbound
from symbiont.records.schema import Provenance

log = logging.getLogger("symbiont.egress")

Transport = Callable[[urllib.request.Request, float], bytes]


def _urlopen(request: urllib.request.Request, timeout_s: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return bytes(response.read())


def _describe(destination: Destination, size: int, provenance: list[Provenance]) -> str:
    datasets = sorted({p.dataset for p in provenance})
    return (
        f"endpoint={destination.endpoint.value} host={urlsplit(destination.url).hostname} "
        f"bytes={size} records={len(provenance)} datasets={datasets or 'none'}"
    )


def post_json(
    destination: Destination,
    body: Mapping[str, object],
    *,
    provenance: Iterable[Provenance] = (),
    timeout_s: float = 300.0,
    transport: Transport = _urlopen,
) -> dict[str, Any]:
    """POST `body` as JSON, return the decoded reply. Raises `EgressRefusedError` before sending."""
    declared = list(provenance)
    wire_bytes = json.dumps(body).encode()
    try:
        check_outbound(destination, declared)
    except EgressRefusedError as refusal:
        log.warning("%s (%s)", refusal, _describe(destination, len(wire_bytes), declared))
        raise
    log.info("egress send %s", _describe(destination, len(wire_bytes), declared))
    headers = {"Content-Type": "application/json"}
    if destination.api_key is not None:
        headers["Authorization"] = f"Bearer {destination.api_key.reveal()}"
    request = urllib.request.Request(destination.url, data=wire_bytes, headers=headers)
    reply: dict[str, Any] = json.loads(transport(request, timeout_s))
    return reply
