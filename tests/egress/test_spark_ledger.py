"""Every call that leaves the machine writes a ledger line; unknown billing is estimated, not $0."""

import json
import urllib.error

import pytest

from symbiont.egress.credentials import ApiKey
from symbiont.egress.spark import Effort, SparkApiError, SparkReplyError, SparkSession
from symbiont.egress.spend import Ledger, SpendCaps, Tier, Usage, estimate_usage
from symbiont.records.schema import Provenance

SAFE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)
GOOD = {
    "choices": [{"message": {"content": "go_to(door)"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 500, "completion_tokens": 40},
}


def spark(tmp_path, transport):
    return SparkSession(
        "m", Tier.CONTRIBUTOR, "r", SpendCaps(15.0, 2.0), ApiKey("test-token"),
        Ledger(tmp_path / "l.jsonl"), (SAFE,), transport,
    )  # fmt: skip


def only_line(tmp_path):
    (line,) = [json.loads(x) for x in (tmp_path / "l.jsonl").read_text().splitlines()]
    return line


def reply_with(body):
    return lambda request, timeout: body if isinstance(body, bytes) else json.dumps(body).encode()


def test_a_normal_call_is_exact_and_not_marked_estimated(tmp_path):
    spark(tmp_path, reply_with(GOOD)).chat("p", Effort.LOW, "g")
    line = only_line(tmp_path)
    assert line["estimated"] is False and "error" not in line and line["prompt"] == 500


def test_a_reply_without_usage_is_estimated_and_still_raises(tmp_path):
    body = {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]}
    with pytest.raises(SparkReplyError, match="usage"):
        spark(tmp_path, reply_with(body)).chat("p", Effort.LOW, "g")
    line = only_line(tmp_path)
    assert line["error"] == "no_usage" and line["estimated"] is True and line["cost_usd"] > 0


def test_a_reply_that_is_not_json_is_estimated_and_raises(tmp_path):
    with pytest.raises(SparkReplyError, match="JSON"):
        spark(tmp_path, reply_with(b"<html>gateway</html>")).chat("p", Effort.LOW, "g")
    line = only_line(tmp_path)
    assert line["error"] == "bad_json" and line["estimated"] is True and line["cost_usd"] > 0


def test_a_timeout_is_estimated_at_the_full_token_room_and_propagates(tmp_path):
    def slow(request, timeout):
        raise TimeoutError("read timed out")

    with pytest.raises(TimeoutError):
        spark(tmp_path, slow).chat("p", Effort.LOW, "g", max_tokens=4000)
    line = only_line(tmp_path)
    assert line["error"] == "TimeoutError" and line["estimated"] is True
    assert line["completion"] == 4000 and line["cost_usd"] > 0


def test_a_rejected_request_is_estimated_on_the_prompt_alone(tmp_path):
    def rejected(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, None)

    with pytest.raises(SparkApiError):
        spark(tmp_path, rejected).chat("p", Effort.LOW, "g", max_tokens=4000)
    line = only_line(tmp_path)
    assert line["error"] == "status 400" and line["estimated"] is True
    assert line["completion"] == 0 and line["prompt"] > 0


def test_a_server_error_is_estimated_at_the_full_token_room(tmp_path):
    def broken(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 503, "down", {}, None)

    with pytest.raises(SparkApiError):
        spark(tmp_path, broken).chat("p", Effort.LOW, "g", max_tokens=4000)
    assert only_line(tmp_path)["completion"] == 4000


def test_the_estimate_is_conservative_about_bytes_per_token():
    usage = estimate_usage(wire_bytes=3000, max_tokens=100, generated=True)
    assert usage == Usage(prompt=1000, cached=0, completion=100, reasoning=0)
    assert estimate_usage(3000, 100, generated=False).completion == 0
