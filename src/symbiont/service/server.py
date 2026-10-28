"""The service's one listener: loopback HTTP in front of `Service.respond`."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from symbiont.service.app import Service

# 7377 spells SYMB on a phone keypad; any free loopback port works for tests.
SERVICE_PORT = 7377
MAX_BODY_BYTES = 1_000_000

log = logging.getLogger("symbiont.service")


def bind(service: Service, port: int = SERVICE_PORT) -> ThreadingHTTPServer:
    """Listen on loopback only; the host is fixed so no caller or config can widen it."""
    return ThreadingHTTPServer(("127.0.0.1", port), _routes_for(service))


def serve(service: Service, port: int = SERVICE_PORT) -> None:
    """Answer requests until interrupted."""
    server = bind(service, port)
    log.info("symbiont service listening on port %d", server.server_address[1])
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _routes_for(service: Service) -> type[BaseHTTPRequestHandler]:
    class Routes(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # http.server dispatches by this name
            response = service.respond(self.path, _json_body(self))
            payload = json.dumps(response.body).encode()
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            """The event log is the record of calls; the stderr access line adds nothing."""

    return Routes


def _json_body(request: BaseHTTPRequestHandler) -> Any:
    """The decoded body, or None when it is absent, too large or not JSON (a 400 downstream)."""
    declared = request.headers.get("Content-Length") or "0"
    try:
        size = int(declared)
        if not 0 < size <= MAX_BODY_BYTES:
            return None
        return json.loads(request.rfile.read(size))
    except ValueError:
        log.warning("request body is unusable (Content-Length %s)", declared[:20])
        return None
