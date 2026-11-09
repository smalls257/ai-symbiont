"""The research-only remote door: provenance decides what leaves, the provider table where."""

import json
import logging
import urllib.request

import pytest

from symbiont.egress import EgressRefusedError
from symbiont.egress.remote_send import (
    REMOTE_HOSTS,
    RemoteDestination,
    RemoteEndpoint,
    check_remote,
    post_remote_json,
)
from symbiont.records.schema import Provenance

SAFE = Provenance(dataset="openhands", license="MIT", remote_safe=True)
PRIVATE = Provenance(dataset="owner-sessions", license="private", remote_safe=False)
SWE_CHAT = Provenance(dataset="SWE-chat", license="research", remote_safe=True)
REMOTE_URL = "https://api.meta.ai/v1/chat/completions"
SECRET_TEXT = "the quick brown fox is private prompt text"


def remote(url: str = REMOTE_URL, endpoint: RemoteEndpoint = RemoteEndpoint.REMOTE_CHAT):
    return RemoteDestination(endpoint, url)


@pytest.mark.parametrize("endpoint", list(RemoteEndpoint))
def test_remote_endpoints_take_remote_safe_records(endpoint):
    check_remote(remote(endpoint=endpoint), [SAFE, SAFE])


@pytest.mark.parametrize("endpoint", list(RemoteEndpoint))
@pytest.mark.parametrize("bad", [[PRIVATE], [SAFE, PRIVATE], [SWE_CHAT], []])
def test_remote_endpoints_refuse_private_or_undeclared_provenance(endpoint, bad):
    with pytest.raises(EgressRefusedError):
        check_remote(remote(endpoint=endpoint), bad)


def test_the_refusal_names_the_dataset_not_any_text():
    with pytest.raises(EgressRefusedError, match="owner-sessions"):
        check_remote(remote(), [PRIVATE])


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://" + "10." + "0.0.5/v1",
        "https://box" + ".local/v1",
        "ftp://x.com",
        "https://box" + ".lan./v1",
        "https://router" + ".fritz.box/v1",
    ],
)
def test_remote_endpoints_refuse_plain_http_private_hosts_and_other_schemes(url):
    with pytest.raises(EgressRefusedError):
        check_remote(remote(url), [SAFE])


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "https://api.meta.ai.evil.example/v1",
        "https://evil.example/api.meta.ai",
        "https://api.meta.ai:8443" + "@evil.example/v1",
    ],
)
def test_remote_endpoints_refuse_any_host_but_the_listed_one(url):
    with pytest.raises(EgressRefusedError, match="not an allowed remote host"):
        check_remote(remote(url), [SAFE])


def test_the_listed_host_passes_with_a_trailing_dot_and_any_case():
    assert "api.meta.ai" in REMOTE_HOSTS
    check_remote(remote("https://API.Meta.AI./v1"), [SAFE])


class FakeTransport:
    def __init__(self):
        self.requests = []

    def __call__(self, request: urllib.request.Request, timeout_s: float) -> bytes:
        self.requests.append(request)
        return json.dumps({}).encode()


def test_a_refused_send_raises_before_the_transport_is_touched():
    transport = FakeTransport()
    with pytest.raises(EgressRefusedError):
        post_remote_json(remote(), {"p": SECRET_TEXT}, provenance=[PRIVATE], transport=transport)
    assert transport.requests == []


def test_the_log_holds_sizes_and_provenance_never_the_text(caplog):
    caplog.set_level(logging.INFO, logger="symbiont.egress")
    post_remote_json(remote(), {"p": SECRET_TEXT}, provenance=[SAFE], transport=FakeTransport())
    with pytest.raises(EgressRefusedError):
        post_remote_json(
            remote(), {"p": SECRET_TEXT}, provenance=[PRIVATE], transport=FakeTransport()
        )
    logged = caplog.text
    assert "bytes=" in logged and "openhands" in logged and "owner-sessions" in logged
    assert "quick brown fox" not in logged
