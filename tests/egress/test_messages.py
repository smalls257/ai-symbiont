"""Every message of a tool-calling history declares its own provenance, tool results included."""

import json

import pytest

from symbiont.egress import EgressRefusedError
from symbiont.egress.credentials import ApiKey
from symbiont.egress.messages import Message, declared_provenance
from symbiont.egress.spark import Effort, SparkSession
from symbiont.egress.spend import Ledger, SpendCaps, Tier
from symbiont.records.schema import Provenance

PUBLIC = Provenance(dataset="swe-rebench-sqlglot", license="CC-BY-4.0", spark_safe=True)
PRIVATE = Provenance(dataset="owner-sessions", license="private", spark_safe=False)
CALL = {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}
REPLY = {
    "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


class FakeTransport:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout_s):
        self.requests.append(request)
        return json.dumps(REPLY).encode()


def spark(tmp_path, transport):
    return SparkSession(
        "m", Tier.CONTRIBUTOR, "r", SpendCaps(15.0, 2.0), ApiKey("test-token"),
        Ledger(tmp_path / "l.jsonl"), (), transport,
    )  # fmt: skip


def history(tool_provenance=(PUBLIC,), assistant_provenance=None):
    start = [Message("system", "fix the issue", (PUBLIC,)), Message("user", "the issue", (PUBLIC,))]
    if assistant_provenance is None:
        call = Message.assistant(None, start, {"tool_calls": [CALL]})
    else:
        call = Message("assistant", None, assistant_provenance, {"tool_calls": [CALL]})
    return [*start, call, Message("tool", "file contents", tool_provenance, {"tool_call_id": "c1"})]


def test_a_message_goes_on_the_wire_with_its_extra_fields_and_no_provenance():
    wire = history()[3].wire()
    assert wire == {"role": "tool", "content": "file contents", "tool_call_id": "c1"}


def test_every_declared_dataset_is_collected_for_the_policy():
    assert declared_provenance(history()) == [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC]


def test_an_undeclared_tool_result_is_refused_before_anything_is_sent(tmp_path):
    transport = FakeTransport()
    with pytest.raises(EgressRefusedError, match=r"message 3 \(tool\)"):
        spark(tmp_path, transport).converse(history(()), [], Effort.LOW, "x")
    assert transport.requests == []


def test_a_private_tool_result_is_refused_before_anything_is_sent(tmp_path):
    transport = FakeTransport()
    with pytest.raises(EgressRefusedError, match="owner-sessions"):
        spark(tmp_path, transport).converse(history((PRIVATE,)), [], Effort.LOW, "x")
    assert transport.requests == []


def test_a_private_tool_result_among_public_ones_still_refuses_the_whole_turn(tmp_path):
    transport = FakeTransport()
    with pytest.raises(EgressRefusedError):
        spark(tmp_path, transport).converse(history((PUBLIC, PRIVATE)), [], Effort.LOW, "x")
    assert transport.requests == []


def test_an_assistant_turn_with_no_provenance_is_refused(tmp_path):
    transport = FakeTransport()
    with pytest.raises(EgressRefusedError, match=r"message 2 \(assistant\)"):
        spark(tmp_path, transport).converse(history(assistant_provenance=()), [], Effort.LOW, "x")
    assert transport.requests == []


def test_a_replayed_private_transcript_is_refused_through_its_assistant_turns(tmp_path):
    private_start = [Message("user", "private question", (PRIVATE,))]
    replay = [*private_start, Message.assistant("private answer", private_start)]
    transport = FakeTransport()
    with pytest.raises(EgressRefusedError, match="owner-sessions"):
        spark(tmp_path, transport).converse(replay, [], Effort.LOW, "x")
    assert transport.requests == []


def test_an_assistant_turn_inherits_the_records_of_the_history_it_answered():
    start = [Message("user", "q", (PUBLIC,)), Message("tool", "t", (PRIVATE,))]
    answer = Message.assistant("a", start)
    assert answer.provenance == (PUBLIC, PRIVATE) and answer.wire() == {
        "role": "assistant",
        "content": "a",
    }
