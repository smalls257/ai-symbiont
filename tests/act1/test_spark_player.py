"""The Spark player turns a game prompt into a Reply, and an empty reply is an error, not a move."""

import json

import pytest

from symbiont.act1.spark_player import spark_reply_fn
from symbiont.egress.credentials import ApiKey
from symbiont.egress.spark import Effort, SparkReplyError, SparkSession
from symbiont.egress.spend import Ledger, SpendCaps, Tier
from symbiont.records.schema import Provenance

SAFE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)


def make_session(tmp_path, content):
    body = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 50},
    }
    return SparkSession(
        "muse-spark-1.3-contributor", Tier.CONTRIBUTOR, "t", SpendCaps(15.0, 2.0), ApiKey("k"),
        Ledger(tmp_path / "l.jsonl"), (SAFE,), lambda request, timeout: json.dumps(body).encode(),
    )  # fmt: skip


def test_the_reply_carries_text_and_server_token_counts(tmp_path):
    reply = spark_reply_fn(make_session(tmp_path, "go_to(door)"), Effort.LOW, "MAP01-s1-low")("p")
    assert reply.text == "go_to(door)" and reply.finish_reason == "stop"
    assert (reply.tokens.prompt, reply.tokens.completion) == (300, 50)


def test_an_empty_reply_raises_instead_of_becoming_a_move(tmp_path):
    play = spark_reply_fn(make_session(tmp_path, None), Effort.LOW, "g")
    with pytest.raises(SparkReplyError):
        play("p")
