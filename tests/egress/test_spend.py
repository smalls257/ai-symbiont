"""The ledger records every priced call and the caps stop the next call before it is sent."""

import json

import pytest

from symbiont.egress.spend import (
    Ledger,
    LedgerEntry,
    SpendCapError,
    SpendCaps,
    Tier,
    Usage,
    caps_from_environment,
    cost_usd,
)


def entry(run="probe", cost=0.5, label="MAP01-s1-low"):
    usage = Usage(prompt=1000, cached=0, completion=100, reasoning=60)
    return LedgerEntry(run, label, "muse-spark-1.3-contributor", Tier.CONTRIBUTOR, usage, cost, 3.2)


def test_contributor_cost_uses_the_price_table():
    usage = Usage(prompt=1_000_000, cached=0, completion=1_000_000, reasoning=0)
    assert cost_usd(Tier.CONTRIBUTOR, usage) == pytest.approx(0.10 + 0.20)
    assert cost_usd(Tier.STANDARD, usage) == pytest.approx(1.25 + 4.25)


def test_cached_prompt_tokens_are_billed_at_the_cached_rate():
    usage = Usage(prompt=1_000_000, cached=1_000_000, completion=0, reasoning=0)
    assert cost_usd(Tier.STANDARD, usage) == pytest.approx(0.15)


def test_an_entry_is_one_json_line_with_counts_and_no_text(tmp_path):
    ledger = Ledger(tmp_path / "spend" / "ledger.jsonl")
    ledger.record(entry())
    line = json.loads((tmp_path / "spend" / "ledger.jsonl").read_text())
    assert line["prompt"] == 1000 and line["reasoning"] == 60 and line["cost_usd"] == 0.5
    assert line["tier"] == "contributor" and line["model"] == "muse-spark-1.3-contributor"
    assert set(line) >= {"ts", "run", "label", "cached", "completion", "seconds"}


def test_spent_sums_the_whole_ledger_or_one_run(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record(entry("a", 0.25))
    ledger.record(entry("b", 0.5))
    assert ledger.spent() == pytest.approx(0.75)
    assert ledger.spent("a") == pytest.approx(0.25)
    assert Ledger(tmp_path / "none.jsonl").spent() == 0.0


def test_the_run_cap_raises_before_the_next_call(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record(entry("probe", 2.0))
    with pytest.raises(SpendCapError, match="run 'probe'"):
        ledger.check_before_call("probe", SpendCaps(total_usd=15.0, run_usd=2.0))
    ledger.check_before_call("other", SpendCaps(total_usd=15.0, run_usd=2.0))


def test_the_total_cap_raises_for_every_run(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record(entry("old", 15.0))
    with pytest.raises(SpendCapError, match="total"):
        ledger.check_before_call("new", SpendCaps(total_usd=15.0, run_usd=2.0))


def test_the_total_cap_comes_from_the_environment_with_a_15_dollar_default(monkeypatch):
    monkeypatch.delenv("SYMBIONT_SPEND_CAP_USD", raising=False)
    assert caps_from_environment(run_usd=2.0) == SpendCaps(15.0, 2.0)
    monkeypatch.setenv("SYMBIONT_SPEND_CAP_USD", "7.5")
    assert caps_from_environment(run_usd=2.0).total_usd == 7.5
    monkeypatch.setenv("SYMBIONT_SPEND_CAP_USD", "lots")
    with pytest.raises(ValueError, match="SYMBIONT_SPEND_CAP_USD"):
        caps_from_environment(run_usd=2.0)


def test_a_torn_ledger_line_raises_instead_of_undercounting(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"run": "a", "cost_usd": 1.0}\n{"run": "a", "cost_us')
    with pytest.raises(ValueError, match="ledger"):
        Ledger(path).spent()
