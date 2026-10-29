"""Which servers the Route B scripts may send prompts to: loopback, or a configured Glimmer host.

Prompts carry lesson text, so a typo'd or pasted --server must stop the script before any request,
never reach an unknown machine. Stdlib only, so the Strix venv and the repo's tests both import it.
"""

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
CONFIGURED_VARS = ("SYMBIONT_GLIMMER_URL", "SYMBIONT_PERSONAL_GLIMMER_URL")


class UnknownServerError(ValueError):
    """A --server that is neither loopback nor the host of a configured Glimmer URL."""


def allowed_hosts(env: Mapping[str, str]) -> frozenset[str]:
    """Loopback plus the host of every configured Glimmer URL that is set."""
    configured = {urlsplit(env[var]).hostname for var in CONFIGURED_VARS if env.get(var)}
    return LOOPBACK | {host for host in configured if host}


def require_glimmer_server(url: str, env: Mapping[str, str] | None = None) -> str:
    """Return `url` when its host is allowed and its scheme is http(s); raise UnknownServerError."""
    parts = urlsplit(url)
    allowed = allowed_hosts(os.environ if env is None else env)
    if parts.scheme not in ("http", "https") or parts.hostname not in allowed:
        raise UnknownServerError(
            f"--server {parts.scheme}://{parts.hostname} is not loopback or a configured Glimmer "
            f"host (set one of {', '.join(CONFIGURED_VARS)})"
        )
    return url
