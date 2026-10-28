"""post_json checks policy before sending, logs sizes and provenance but never text, and raises."""

import json
import logging
import urllib.request

import pytest

from symbiont.egress import Destination, EgressRefusedError, Endpoint, post_json
from symbiont.records.schema import Provenance

SAFE = Provenance(dataset="openhands", license="MIT", spark_safe=True)
PRIVATE = Provenance(dataset="owner-sessions", license="private", spark_safe=False)
SECRET_TEXT = "the quick brown fox is private prompt text"
GLIMMER = Destination(Endpoint.LOCAL_GLIMMER, "http://127.0.0.1:8081/v1/chat/completions")
SPARK = Destination(Endpoint.SPARK, "https://api.meta.ai/v1")


class FakeTransport:
    def __init__(self, reply: dict):
        self.reply, self.requests = reply, []

    def __call__(self, request: urllib.request.Request, timeout_s: float) -> bytes:
        self.requests.append((request, timeout_s))
        return json.dumps(self.reply).encode()


def test_a_local_post_sends_the_body_unchanged_and_returns_the_reply():
    transport = FakeTransport({"ok": 1})
    body = {"model": "m", "messages": [{"role": "user", "content": SECRET_TEXT}]}
    reply = post_json(GLIMMER, body, timeout_s=7, transport=transport)
    request, timeout = transport.requests[0]
    assert reply == {"ok": 1} and timeout == 7
    assert json.loads(request.data) == body
    assert request.get_header("Content-type") == "application/json"


def test_a_refused_send_raises_before_the_transport_is_touched():
    transport = FakeTransport({})
    with pytest.raises(EgressRefusedError):
        post_json(SPARK, {"p": SECRET_TEXT}, provenance=[PRIVATE], transport=transport)
    assert transport.requests == []


def test_the_log_holds_sizes_and_provenance_never_the_text(caplog):
    caplog.set_level(logging.INFO, logger="symbiont.egress")
    post_json(SPARK, {"p": SECRET_TEXT}, provenance=[SAFE], transport=FakeTransport({}))
    with pytest.raises(EgressRefusedError):
        post_json(SPARK, {"p": SECRET_TEXT}, provenance=[PRIVATE], transport=FakeTransport({}))
    logged = caplog.text
    assert "bytes=" in logged and "openhands" in logged and "owner-sessions" in logged
    assert "quick brown fox" not in logged


def test_a_transport_failure_propagates():
    def broken(request, timeout_s):
        raise TimeoutError("down")

    with pytest.raises(TimeoutError):
        post_json(GLIMMER, {}, transport=broken)
