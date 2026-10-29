"""chat_reply keeps its behavior for local Glimmer now that it goes through the egress module."""

import io
import json

import pytest

from symbiont.act1.glimmer import TokenUsage, chat_reply, plain_and_personal
from symbiont.egress import EgressRefusedError, client


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
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }
        return _Response(json.dumps(reply).encode())

    monkeypatch.setattr(client._OPENER, "open", fake_urlopen)
    reply = chat_reply("http://127.0.0.1:8081/v1/", "m", "hello", timeout_s=9)
    assert (reply.text, reply.finish_reason, reply.reasoning_chars) == ("walk_to(exit)", "stop", 3)
    assert seen["url"] == "http://127.0.0.1:8081/v1/chat/completions" and seen["timeout"] == 9
    assert seen["body"]["messages"][1] == {"role": "user", "content": "hello"}
    assert reply.tokens == TokenUsage(12, 3)
    assert "lora" not in seen["body"]


def test_chat_reply_refuses_a_public_host():
    with pytest.raises(EgressRefusedError):
        chat_reply("https://api.example.com/v1", "m", "hello")


def captured_bodies(monkeypatch):
    bodies = []

    def fake_urlopen(request, timeout):
        bodies.append(json.loads(request.data))
        reply = {
            "choices": [{"message": {"content": "turn(90)"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        return _Response(json.dumps(reply).encode())

    monkeypatch.setattr(client._OPENER, "open", fake_urlopen)
    return bodies


def test_plain_and_personal_send_the_same_request_except_the_adapter_scales(monkeypatch):
    bodies = captured_bodies(monkeypatch)
    plain, personal = plain_and_personal("http://127.0.0.1:8093/v1", "glimmer", 2, 1)
    plain.reply("the same prompt")
    personal.reply("the same prompt")
    assert bodies[0]["lora"] == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 0.0}]
    assert bodies[1]["lora"] == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 1.0}]
    del bodies[0]["lora"], bodies[1]["lora"]
    assert bodies[0] == bodies[1]
    assert (plain.name, personal.name) == ("glimmer_plain", "glimmer_personal")


def test_an_adapter_the_server_does_not_hold_is_refused():
    with pytest.raises(ValueError, match="adapter 2"):
        plain_and_personal("http://127.0.0.1:8093/v1", "glimmer", 2, 2)
