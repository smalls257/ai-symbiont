"""Route B scripts send prompts only to loopback or a configured Glimmer host."""

import sys
from pathlib import Path

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"


@pytest.fixture
def hosts(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEB))
    sys.modules.pop("glimmer_hosts", None)
    import glimmer_hosts

    yield glimmer_hosts
    sys.modules.pop("glimmer_hosts", None)


CONFIGURED = {"SYMBIONT_GLIMMER_URL": "http://glimmer.example.invalid:8081/v1"}


def test_loopback_and_the_configured_glimmer_host_are_allowed(hosts):
    assert hosts.require_glimmer_server("http://127.0.0.1:8080", {}) == "http://127.0.0.1:8080"
    assert hosts.require_glimmer_server("http://localhost:8080", {})
    assert hosts.require_glimmer_server("http://glimmer.example.invalid:8082", CONFIGURED)


def test_an_unconfigured_host_or_a_non_http_scheme_is_refused_before_any_request(hosts):
    with pytest.raises(hosts.UnknownServerError, match="not loopback or a configured Glimmer"):
        hosts.require_glimmer_server("https://api.example.invalid", CONFIGURED)
    with pytest.raises(hosts.UnknownServerError):
        hosts.require_glimmer_server("file://127.0.0.1/etc/passwd", CONFIGURED)
    with pytest.raises(hosts.UnknownServerError):
        hosts.require_glimmer_server("http://glimmer.example.invalid:8082", {})
