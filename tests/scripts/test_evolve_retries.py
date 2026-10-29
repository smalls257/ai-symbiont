"""Transient Spark failures are retried with logged waits; anything else raises at once."""

import logging
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import spark_players  # noqa: E402 - needs the scripts path added above

from symbiont.act1.glimmer import Reply  # noqa: E402
from symbiont.egress.spark import SparkApiError, SparkReplyError  # noqa: E402

pytestmark = pytest.mark.periphery
OK = Reply("turn(90)", "stop", 0)


def failing_then_ok(errors):
    pending = list(errors)

    def reply(prompt):
        if pending:
            raise pending.pop(0)
        return OK

    return reply


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SparkApiError("status 429: slow down"), True),
        (SparkApiError("status 503: busy"), True),
        (SparkApiError("status 401: bad key"), False),
        (SparkApiError("status 400: bad request"), False),
        (urllib.error.URLError("reset"), True),
        (TimeoutError("slow"), True),
        (SparkReplyError("no content"), False),
        (ValueError("ours"), False),
    ],
)
def test_which_errors_are_transient(error, expected):
    assert spark_players.is_transient(error) is expected


def test_a_transient_error_is_retried_with_growing_waits_and_the_reply_comes_back():
    waits = []
    reply = spark_players.with_retries(
        failing_then_ok([SparkApiError("status 429: x"), SparkApiError("status 503: y")]),
        waits=(1.0, 2.0, 3.0),
        sleep=waits.append,
    )
    assert reply("p") == OK and waits == [1.0, 2.0]


def test_when_the_waits_run_out_the_last_error_is_raised():
    errors = [SparkApiError(f"status 503: try {n}") for n in range(5)]
    waits = []
    reply = spark_players.with_retries(
        failing_then_ok(errors), waits=(1.0, 2.0), sleep=waits.append
    )
    with pytest.raises(SparkApiError, match="try 2"):
        reply("p")
    assert waits == [1.0, 2.0]


def test_a_non_transient_error_is_raised_at_once_without_waiting():
    waits = []
    reply = spark_players.with_retries(
        failing_then_ok([SparkApiError("status 401: bad key")]), sleep=waits.append
    )
    with pytest.raises(SparkApiError, match="401"):
        reply("p")
    assert waits == []


def test_a_retry_is_logged_with_the_error_class_and_never_the_prompt(caplog):
    caplog.set_level(logging.WARNING)
    reply = spark_players.with_retries(
        failing_then_ok([SparkApiError("status 429: x")]), sleep=lambda _s: None
    )
    reply("SECRET PROMPT TEXT")
    assert "SparkApiError" in caplog.text and "attempt 1" in caplog.text
    assert "SECRET PROMPT TEXT" not in caplog.text


def test_a_retrying_session_asks_again_after_a_transient_error_and_passes_max_tokens(tmp_path):
    import json

    from symbiont.egress.credentials import ApiKey
    from symbiont.egress.spark import Effort, SparkSession
    from symbiont.egress.spend import Ledger, SpendCaps, Tier

    calls = []

    def transport(request, timeout_s):
        calls.append(json.loads(request.data)["max_tokens"])
        if len(calls) == 1:
            raise urllib.error.URLError("nodename nor servname provided")
        body = {
            "choices": [{"message": {"content": "GENERAL"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        return json.dumps(body).encode()

    inner = SparkSession(
        "m", Tier.CONTRIBUTOR, "r", SpendCaps(15.0, 3.0), ApiKey("k"),
        Ledger(tmp_path / "l.jsonl"), (spark_players.PROVENANCE,), transport,
    )  # fmt: skip
    waits = []
    session = spark_players.RetryingSession(inner, waits=(1.0, 2.0), sleep=waits.append)
    assert session.run == "r"
    assert session.chat("p", Effort.MEDIUM, "label", 9999).text == "GENERAL"
    assert waits == [1.0] and calls == [9999, 9999]


def test_a_retrying_session_raises_a_non_transient_error_at_once(tmp_path):
    from symbiont.egress.credentials import ApiKey
    from symbiont.egress.spark import Effort, SparkSession
    from symbiont.egress.spend import Ledger, SpendCaps, Tier

    def transport(request, timeout_s):
        raise ValueError("ours")

    inner = SparkSession(
        "m", Tier.CONTRIBUTOR, "r", SpendCaps(15.0, 3.0), ApiKey("k"),
        Ledger(tmp_path / "l.jsonl"), (spark_players.PROVENANCE,), transport,
    )  # fmt: skip
    waits = []
    with pytest.raises(ValueError, match="ours"):
        spark_players.RetryingSession(inner, sleep=waits.append).chat("p", Effort.LOW, "l")
    assert waits == []
