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
