"""A real service on an ephemeral loopback port, for tests that talk to it over HTTP.

Tests must always pass the port they get here: the default port may be the developer's own
running service.
"""

import threading
from contextlib import contextmanager
from pathlib import Path

from symbiont.service import server
from symbiont.service.app import Service, ServiceMode
from symbiont.service.wiring import Guards, open_service
from symbiont.store.repos import RepoRegistry


@contextmanager
def serving(data_dir: Path):
    """Yield `(service, port)` for a service over `data_dir`, with its repository answers."""
    data_dir.mkdir(parents=True, exist_ok=True)
    guards = Guards(repos=RepoRegistry(data_dir))
    service: Service = open_service(data_dir, ServiceMode.WARN_AND_RECALL, guards=guards)
    httpd = server.bind(service, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield service, httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()
