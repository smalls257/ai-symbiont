"""A multi-turn, tool-calling turn through the Spark session: priced, capped, privacy-checked."""

import json

import pytest

from symbiont.egress import EgressRefusedError
from symbiont.egress.credentials import ApiKey
from symbiont.egress.messages import Message
from symbiont.egress.policy import Endpoint
from symbiont.egress.spark import Effort, SparkReplyError, SparkSession
from symbiont.egress.spend import Ledger, SpendCapError, SpendCaps, Tier
from symbiont.records.schema import Provenance

PUBLIC = Provenance(dataset="swe-rebench-sqlglot", license="CC-BY-4.0", spark_safe=True)
PRIVATE = Provenance(dataset="owner-sessions", license="private", spark_safe=False)
TOOLS = [{"type": "function", "function": {"name": "bash", "parameters": {"type": "object"}}}]
HISTORY = [
    Message("system", "fix the issue", (PUBLIC,)),
    Message("user", "the issue", (PUBLIC,)),
]


def tool_reply(prompt=1000, completion=50):
    call = {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}
    return {
        "choices": [
            {"message": {"content": None, "tool_calls": [call]}, "finish_reason": "tool_calls"}
        ],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


class FakeTransport:
    def __init__(self, body):
        self.body, self.requests = body, []

    def __call__(self, request, timeout_s):
        self.requests.append(request)
        return json.dumps(self.body).encode()


ROOMY = SpendCaps(15.0, 2.0)


def session(tmp_path, transport, provenance=(PUBLIC,), caps=ROOMY, **extra):
    return SparkSession(
        "muse-spark-1.3-contributor", Tier.CONTRIBUTOR, "teacher-probe", caps,
        ApiKey("test-token"), Ledger(tmp_path / "ledger.jsonl"), provenance, transport, **extra,
    )  # fmt: skip


def test_a_turn_sends_history_and_tools_and_returns_the_tool_call(tmp_path):
    transport = FakeTransport(tool_reply())
    spark = session(tmp_path, transport)
    out = spark.converse(HISTORY, TOOLS, Effort.LOW, "sqlglot-1367-step1")
    body = json.loads(transport.requests[0].data)
    assert body["messages"] == [m.wire() for m in HISTORY] and body["tools"] == TOOLS
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "bash"
    (entry,) = spark.ledger.entries()
    assert entry["label"] == "sqlglot-1367-step1" and entry["prompt"] == 1000
    assert entry["cost_usd"] == pytest.approx(1000 * 0.10 / 1e6 + 50 * 0.20 / 1e6)


def test_a_turn_stops_at_the_cap_before_sending(tmp_path):
    transport = FakeTransport(tool_reply(prompt=10_000_000))
    spark = session(tmp_path, transport, caps=SpendCaps(15.0, 0.5))
    spark.converse(HISTORY, TOOLS, Effort.LOW, "first")
    with pytest.raises(SpendCapError):
        spark.converse(HISTORY, TOOLS, Effort.LOW, "second")
    assert len(transport.requests) == 1


def test_a_turn_refuses_private_provenance_and_a_reply_without_usage(tmp_path):
    with pytest.raises(EgressRefusedError):
        session(tmp_path, FakeTransport(tool_reply())).converse(
            [Message("user", "q", (PRIVATE,))], TOOLS, Effort.LOW, "x"
        )
    no_usage = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
    with pytest.raises(SparkReplyError):
        session(tmp_path, FakeTransport(no_usage)).converse(HISTORY, TOOLS, Effort.LOW, "y")


def test_a_wonder_session_names_the_wonder_endpoint(tmp_path):
    transport = FakeTransport(tool_reply())
    spark = session(tmp_path, transport, endpoint=Endpoint.WONDER)
    spark.converse(HISTORY, TOOLS, Effort.LOW, "w")
    assert transport.requests[0].full_url == "https://api.meta.ai/v1/chat/completions"
