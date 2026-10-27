"""chat_reply keeps its behaviour for local Glimmer now that it goes through the egress module."""

import io
import json
import urllib.request

import pytest

from symbiont.act1.glimmer import chat_reply
from symbiont.egress import EgressRefusedError


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_chat_reply_posts_the_same_request_and_parses_the_reply(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["body"], seen["timeout"] = (
            request.full_url,
            json.loads(request.data),
            timeout,
        )
        reply = {
            "choices": [
                {
                    "message": {"content": " walk_to(exit) ", "reasoning_content": "abc"},
                    "finish_reason": "stop",
                }
            ]
        }
        return _Response(json.dumps(reply).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    reply = chat_reply("http://127.0.0.1:8081/v1/", "m", "hello", timeout_s=9)
    assert (reply.text, reply.finish_reason, reply.reasoning_chars) == ("walk_to(exit)", "stop", 3)
    assert seen["url"] == "http://127.0.0.1:8081/v1/chat/completions" and seen["timeout"] == 9
    assert seen["body"]["messages"][1] == {"role": "user", "content": "hello"}


def test_chat_reply_refuses_a_public_host():
    with pytest.raises(EgressRefusedError):
        chat_reply("https://api.example.com/v1", "m", "hello")
