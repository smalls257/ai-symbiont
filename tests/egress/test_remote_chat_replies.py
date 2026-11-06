"""converse and chat both raise on an empty reply or a refusal; a tool call is a real reply."""

import json

import pytest

from symbiont.egress.credentials import ApiKey
from symbiont.egress.messages import Message
from symbiont.egress.remote_chat import Effort, RemoteChatSession, RemoteReplyError, provider
from symbiont.egress.spend import Ledger, SpendCaps, Tier
from symbiont.records.schema import Provenance

PUBLIC = Provenance(dataset="swe-rebench-sqlglot", license="CC-BY-4.0", remote_safe=True)
CALL = {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}
USAGE = {"prompt_tokens": 100, "completion_tokens": 20}
HISTORY = [Message("user", "the issue", (PUBLIC,))]


def reply(message, finish="stop"):
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": USAGE}


def chat_session(tmp_path, body):
    return RemoteChatSession(
        provider("meta"), "m", Tier.CONTRIBUTOR, "r", SpendCaps(15.0, 2.0), ApiKey("test-token"),
        Ledger(tmp_path / "l.jsonl"), (PUBLIC,), lambda request, timeout: json.dumps(body).encode(),
    )  # fmt: skip


def turn(tmp_path, body):
    return chat_session(tmp_path, body).converse(HISTORY, [], Effort.LOW, "g")


def test_a_tool_call_without_text_is_a_real_reply(tmp_path):
    out = turn(tmp_path, reply({"content": None, "tool_calls": [CALL]}, "tool_calls"))
    assert out["choices"][0]["message"]["tool_calls"] == [CALL]


@pytest.mark.parametrize("message", [{"content": None}, {"content": ""}, {"content": "  \n"}])
def test_a_turn_with_neither_text_nor_a_tool_call_raises(tmp_path, message):
    with pytest.raises(RemoteReplyError, match="no content"):
        turn(tmp_path, reply(message))


def test_a_refusal_raises_in_a_turn_and_in_chat(tmp_path):
    refusal = reply({"content": None, "refusal": "I can't help with that"})
    with pytest.raises(RemoteReplyError, match="refused"):
        turn(tmp_path, refusal)
    with pytest.raises(RemoteReplyError, match="refused"):
        chat_session(tmp_path, refusal).chat("p", Effort.LOW, "g")


def test_a_content_filter_stop_is_a_refusal(tmp_path):
    with pytest.raises(RemoteReplyError, match="refused"):
        turn(tmp_path, reply({"content": "partial"}, "content_filter"))


def test_a_reply_with_no_choices_raises_and_is_still_priced(tmp_path):
    body = {"choices": [], "usage": USAGE}
    session = chat_session(tmp_path, body)
    with pytest.raises(RemoteReplyError, match="no choices"):
        session.converse(HISTORY, [], Effort.LOW, "g")
    assert session.ledger.spent() > 0


def test_chat_rejects_whitespace_only_text(tmp_path):
    with pytest.raises(RemoteReplyError, match="no content"):
        chat_session(tmp_path, reply({"content": " "})).chat("p", Effort.LOW, "g")
