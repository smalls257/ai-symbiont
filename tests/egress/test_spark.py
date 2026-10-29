"""The Spark session prices each call into the ledger; an empty reply never becomes a move."""

import json
import urllib.error

import pytest

from symbiont.egress import EgressRefusedError
from symbiont.egress.credentials import ApiKey
from symbiont.egress.spark import Effort, SparkApiError, SparkReplyError, SparkSession
from symbiont.egress.spend import Ledger, SpendCapError, SpendCaps, Tier
from symbiont.records.schema import Provenance

SAFE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)
PRIVATE = Provenance(dataset="owner-sessions", license="private", spark_safe=False)
PROMPT = "the prompt text must never reach a log"


def reply_body(content="go_to(door)", finish="stop", completion=40, reasoning=30):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": completion,
            "prompt_tokens_details": {"cached_tokens": 100},
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        },
    }


class FakeTransport:
    def __init__(self, body):
        self.body, self.requests = body, []

    def __call__(self, request, timeout_s):
        self.requests.append(request)
        return json.dumps(self.body).encode()


ROOMY = SpendCaps(15.0, 2.0)


def session(tmp_path, transport, provenance=(SAFE,), caps=ROOMY):
    return SparkSession(
        "muse-spark-1.3-contributor", Tier.CONTRIBUTOR, "probe", caps, ApiKey("test-token"),
        Ledger(tmp_path / "ledger.jsonl"), provenance, transport,
    )  # fmt: skip


def test_a_call_posts_to_the_contributor_lane_and_writes_one_ledger_line(tmp_path):
    transport = FakeTransport(reply_body())
    spark = session(tmp_path, transport)
    reply = spark.chat(PROMPT, Effort.LOW, "MAP01-s1-low")
    request = transport.requests[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.meta.ai/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-token"
    assert body["model"] == "muse-spark-1.3-contributor" and body["reasoning_effort"] == "low"
    assert body["max_tokens"] >= 1000  # room for reasoning, not 20
    assert reply.text == "go_to(door)" and reply.usage.reasoning == 30 and reply.usage.cached == 100
    line = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert line["label"] == "MAP01-s1-low" and line["prompt"] == 500 and line["cost_usd"] > 0


def test_empty_content_raises_and_the_tokens_it_burned_are_still_billed(tmp_path):
    spark = session(tmp_path, FakeTransport(reply_body(content=None, finish="length")))
    with pytest.raises(SparkReplyError, match="finish_reason=length"):
        spark.chat(PROMPT, Effort.LOW, "g")
    assert Ledger(tmp_path / "ledger.jsonl").spent("probe") > 0


def test_a_reply_without_usage_raises(tmp_path):
    body = reply_body()
    del body["usage"]
    with pytest.raises(SparkReplyError, match="usage"):
        session(tmp_path, FakeTransport(body)).chat(PROMPT, Effort.LOW, "g")


def test_the_cap_raises_before_anything_is_sent(tmp_path):
    transport = FakeTransport(reply_body())
    spark = session(tmp_path, transport, caps=SpendCaps(15.0, 0.0))
    with pytest.raises(SpendCapError):
        spark.chat(PROMPT, Effort.LOW, "g")
    assert transport.requests == []


def test_private_provenance_is_refused_before_anything_is_sent(tmp_path):
    transport = FakeTransport(reply_body())
    with pytest.raises(EgressRefusedError):
        session(tmp_path, transport, provenance=(PRIVATE,)).chat(PROMPT, Effort.LOW, "g")
    assert transport.requests == []


def test_an_http_error_becomes_an_api_error_with_the_status(tmp_path):
    def failing(request, timeout_s):
        raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, None)

    with pytest.raises(SparkApiError, match="400"):
        session(tmp_path, failing).chat(PROMPT, Effort.LOW, "g")


def test_none_is_not_an_effort():
    assert "none" not in {effort.value for effort in Effort}
    assert {e.value for e in Effort} == {"minimal", "low", "medium", "high", "xhigh", "max"}


def test_the_log_never_holds_the_prompt(tmp_path, caplog):
    caplog.set_level("DEBUG")
    session(tmp_path, FakeTransport(reply_body())).chat(PROMPT, Effort.LOW, "g")
    assert "never reach a log" not in caplog.text and "test-token" not in caplog.text
