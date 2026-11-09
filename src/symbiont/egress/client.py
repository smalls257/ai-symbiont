"""The thin client: policy first, then one POST to a local server, logging sizes only.

A refused or failed send raises, never returns an empty reply, and the body is never logged. The
only module in the published package allowed to open a connection (semgrep sym-single-egress);
it carries no credential, because no local endpoint takes one.
"""

import json
import logging
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from symbiont.egress.policy import Destination, EgressRefusedError, check_outbound, host_of

log = logging.getLogger("symbiont.egress")

Transport = Callable[[urllib.request.Request, float], bytes]


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect.

    urllib would re-send our headers to whatever host `Location` names, and turns a 301/302/303
    POST into a GET. Returning None makes the opener raise the 3xx as an HTTPError.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Refuse: nothing is followed."""
        return


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def open_without_redirects(request: urllib.request.Request, timeout_s: float) -> bytes:
    """The default transport: one request, no redirects; raises HTTPError on a 3xx, 4xx or 5xx."""
    with _OPENER.open(request, timeout=timeout_s) as response:
        return bytes(response.read())


def post_json(
    destination: Destination,
    body: Mapping[str, object],
    *,
    timeout_s: float = 300.0,
    transport: Transport = open_without_redirects,
) -> dict[str, Any]:
    """POST `body` as JSON, return the decoded reply. Raises `EgressRefusedError` before sending."""
    wire_bytes = json.dumps(body).encode()
    described = (
        f"endpoint={destination.endpoint.value} host={host_of(destination.url)} "
        f"bytes={len(wire_bytes)}"
    )
    try:
        check_outbound(destination)
    except EgressRefusedError as refusal:
        log.warning("%s (%s)", refusal, described)
        raise
    log.info("egress send %s", described)
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(destination.url, data=wire_bytes, headers=headers)
    reply: dict[str, Any] = json.loads(transport(request, timeout_s))
    return reply
