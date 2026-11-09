"""The research-only LAN door: Glimmer may sit on loopback or the home LAN, never a public host."""

import json

import pytest

from symbiont.egress import EgressRefusedError
from symbiont.egress.lan_send import check_glimmer, post_glimmer_json


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8081/v1",
        "http://localhost:8081/v1",
        "http://glimmerbox:8081/v1",
        "http://lab" + ".lan/v1",
        "http://" + "192.168." + "0.9:8081/v1",
        "http://box" + ".lan./v1",
        "http://printer" + ".localdomain/v1",
        "http://router" + ".fritz.box/v1",
    ],
)
def test_glimmer_reaches_loopback_or_lan(url):
    check_glimmer(url)


@pytest.mark.parametrize(
    "url", ["https://api.meta.ai/v1", "https://example.com/v1", "ftp://127.0.0.1/x", "http:///v1"]
)
def test_glimmer_refuses_a_public_host_or_a_bad_url(url):
    with pytest.raises(EgressRefusedError):
        check_glimmer(url)


def test_a_refused_send_never_touches_the_transport():
    sent = []

    def transport(request, timeout_s):
        sent.append(request)
        return b"{}"

    with pytest.raises(EgressRefusedError):
        post_glimmer_json("https://api.meta.ai/v1", {"p": 1}, transport=transport)
    assert sent == []


def test_a_lan_post_sends_the_body_and_returns_the_reply():
    sent = []

    def transport(request, timeout_s):
        sent.append((json.loads(request.data), timeout_s))
        return b'{"ok": 1}'

    reply = post_glimmer_json(
        "http://127.0.0.1:8081/v1", {"p": 1}, timeout_s=3, transport=transport
    )
    assert reply == {"ok": 1} and sent == [({"p": 1}, 3)]
