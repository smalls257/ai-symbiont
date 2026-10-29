"""SparkSession reserves a conservative estimate before sending and settles at the real cost."""

import json

import pytest

from symbiont.egress.credentials import ApiKey
from symbiont.egress.spark import Effort, SparkSession
from symbiont.egress.spend import Ledger, SpendCapError, SpendCaps, Tier, estimate_call_usd
from symbiont.records.schema import Provenance

SAFE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)
GOOD = {
    "choices": [{"message": {"content": "go_to(door)"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 500, "completion_tokens": 40},
}


def spark(tmp_path, caps, transport):
    return SparkSession(
        "m", Tier.CONTRIBUTOR, "r", caps, ApiKey("test-token"),
        Ledger(tmp_path / "l.jsonl"), (SAFE,), transport,
    )  # fmt: skip


def test_the_estimate_is_max_tokens_times_the_output_price_plus_the_prompt():
    cost = estimate_call_usd(Tier.CONTRIBUTOR, wire_bytes=3000, max_tokens=1000)
    assert cost == pytest.approx((1000 * 0.10 + 1000 * 0.20) / 1e6)


def test_a_call_whose_worst_case_would_pass_the_cap_is_refused_before_sending(tmp_path):
    sent = []
    caps = SpendCaps(total_usd=0.0001, run_usd=None)  # worst case of a 4096-token reply is ~$0.0008

    def transport(request, timeout):
        sent.append(request)
        return json.dumps(GOOD).encode()

    with pytest.raises(SpendCapError):
        spark(tmp_path, caps, transport).chat("p", Effort.LOW, "g")
    assert sent == []


def test_the_settled_line_replaces_the_reservation(tmp_path):
    session = spark(tmp_path, SpendCaps(15.0, 2.0), lambda r, t: json.dumps(GOOD).encode())
    session.chat("p", Effort.LOW, "g")
    (row,) = session.ledger.entries()
    assert row["prompt"] == 500 and row["estimated"] is False
    assert session.ledger.spent() == pytest.approx((500 * 0.10 + 40 * 0.20) / 1e6)
