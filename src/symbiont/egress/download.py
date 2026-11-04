"""GET-only downloads of public model files from Hugging Face; the second door in `egress`.

https only, a host allowlist checked on the URL and on every redirect, an exact-size check and a
temp file renamed atomically. It sends no payload and no credential and logs host and path, never
the (signed) query string.
"""

import json
import logging
import os
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, override
from urllib.parse import quote, urlsplit

from symbiont.egress.policy import EgressRefusedError

log = logging.getLogger("symbiont.egress")

# huggingface.co serves the API and the first hop of a file URL; the file bytes come from its CDN,
# measured 2026-11: us.aws.cdn.hf.co (and, in other regions or earlier, cas-bridge.xethub.hf.co
# and cdn-lfs*.hf.co). Every one of those ends in `.hf.co`, Hugging Face's own domain.
HF_PRIMARY_HOST = "huggingface.co"
HF = f"https://{HF_PRIMARY_HOST}"
HF_CDN_SUFFIX = ".hf.co"
CHUNK_BYTES = 1 << 20
CONNECT_TIMEOUT_S = 60.0

Progress = Callable[[int, int | None], None]
Opener = Callable[[urllib.request.Request, float], Any]


class DownloadError(RuntimeError):
    """A download failed or came back wrong; the message names the host, path and what was seen."""


def listing_url(repo: str, folder: str = "") -> str:
    """The Hugging Face API address that lists `folder` of `repo`, recursively."""
    where = f"/{quote(folder)}" if folder else ""
    return f"{HF}/api/models/{repo}/tree/main{where}?recursive=1"


def file_url(repo: str, path: str) -> str:
    """The address of `path` in `repo` at its main branch."""
    return f"{HF}/{repo}/resolve/main/{quote(path)}"


def check_download_url(url: str) -> None:
    """Raise EgressRefusedError unless `url` is https on huggingface.co or its `.hf.co` CDN."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https":
        raise EgressRefusedError(f"download refused: {parts.scheme or 'no'} scheme, https only")
    if host != HF_PRIMARY_HOST and not host.endswith(HF_CDN_SUFFIX):
        raise EgressRefusedError(
            f"download refused: host {host!r} is not {HF_PRIMARY_HOST} or a {HF_CDN_SUFFIX} host"
        )


class _AllowlistedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to an allowlisted https host, so a hijacked Location goes nowhere."""

    @override
    def redirect_request(self, *args: Any, **kwargs: Any) -> Any:
        """Check the target (`newurl`, the sixth argument), then let urllib build the follow-up."""
        check_download_url(args[5] if len(args) > 5 else kwargs["newurl"])
        return super().redirect_request(*args, **kwargs)


def _open(request: urllib.request.Request, timeout_s: float) -> Any:
    """The default opener: allowlisted redirects only."""
    return urllib.request.build_opener(_AllowlistedRedirects).open(request, timeout=timeout_s)


def _described(url: str) -> str:
    """Host and path of a URL, without its (possibly signed) query."""
    parts = urlsplit(url)
    return f"{parts.hostname}{parts.path}"


def _request(url: str, opener: Opener) -> Any:
    """Open `url` with a GET after the allowlist check; HTTP errors become DownloadError."""
    check_download_url(url)
    try:
        return opener(urllib.request.Request(url, method="GET"), CONNECT_TIMEOUT_S)
    except OSError as failed:  # URLError and HTTPError are OSErrors
        raise DownloadError(f"GET {_described(url)} failed: {failed}") from failed


def get_json(url: str, opener: Opener = _open) -> Any:
    """GET `url` and decode its JSON; DownloadError when it fails or is not JSON."""
    with _request(url, opener) as response:
        body = response.read()
    log.info("egress download json %s bytes=%d", _described(url), len(body))
    try:
        return json.loads(body)
    except ValueError as unreadable:
        raise DownloadError(f"GET {_described(url)} did not answer JSON") from unreadable


def _stream(response: Any, sink: Any, expected: int, progress: Progress | None) -> int:
    """Copy `response` into `sink` in chunks, reporting progress; returns the bytes copied."""
    written = 0
    for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
        sink.write(chunk)
        written += len(chunk)
        if progress is not None:
            progress(written, expected)
    return written


def download_file(
    url: str,
    destination: Path,
    expected_size: int,
    progress: Progress | None = None,
    opener: Opener = _open,
) -> int:
    """GET `url` into `destination` via a temp file; returns the bytes written.

    Raises DownloadError (no partial file left) unless exactly `expected_size` bytes arrive.
    """
    check_download_url(url)  # before any folder or file is created
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    written = 0
    try:
        with _request(url, opener) as response, partial.open("wb") as sink:
            written = _stream(response, sink, expected_size, progress)
    except EgressRefusedError:
        partial.unlink(missing_ok=True)
        raise  # a redirect left the allowlist: a refusal, not a broken connection
    except OSError as failed:
        partial.unlink(missing_ok=True)
        raise DownloadError(f"GET {_described(url)} failed: {failed}") from failed
    if written != expected_size:
        partial.unlink(missing_ok=True)
        raise DownloadError(f"GET {_described(url)} gave {written} bytes, expected {expected_size}")
    os.replace(partial, destination)
    log.info("egress download file %s bytes=%d", _described(url), written)
    return written
