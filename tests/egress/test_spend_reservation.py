"""A call reserves its worst-case cost under a file lock, so concurrent callers cannot overshoot."""

import subprocess
import sys
import threading

import pytest

from symbiont.egress.spend import (
    Ledger,
    LedgerEntry,
    SpendCapError,
    SpendCaps,
    Tier,
    Usage,
)

CAPS = SpendCaps(total_usd=1.0, run_usd=None)


def settled(cost):
    usage = Usage(prompt=100, cached=0, completion=10, reasoning=0)
    return LedgerEntry("run", "g", "m", Tier.CONTRIBUTOR, usage, cost, 1.0)


def test_a_reservation_counts_until_it_is_settled_at_the_real_cost(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    call = ledger.reserve("run", CAPS, 0.5, "g")
    assert ledger.spent() == pytest.approx(0.5)
    ledger.settle(call, settled(0.1))
    assert ledger.spent() == pytest.approx(0.1)
    assert [row["cost_usd"] for row in ledger.entries()] == [0.1]


def test_a_released_reservation_leaves_no_trace(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.release(ledger.reserve("run", CAPS, 0.5, "g"))
    assert ledger.spent() == 0.0 and ledger.entries() == []


def test_the_cap_check_includes_the_estimate_of_the_next_call(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.settle(ledger.reserve("run", CAPS, 0.1, "a"), settled(0.9))
    with pytest.raises(SpendCapError, match="total"):
        ledger.reserve("run", CAPS, 0.2, "b")
    ledger.reserve("run", CAPS, 0.05, "c")


def test_the_run_cap_includes_the_estimate_too(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    caps = SpendCaps(total_usd=15.0, run_usd=0.3)
    ledger.reserve("run", caps, 0.2, "a")
    with pytest.raises(SpendCapError, match="run 'run'"):
        ledger.reserve("run", caps, 0.2, "b")
    ledger.reserve("other", caps, 0.2, "c")


def test_threads_with_their_own_ledger_objects_cannot_overshoot(tmp_path):
    path = tmp_path / "l.jsonl"
    outcomes = []

    def attempt():
        try:
            Ledger(path).reserve("run", CAPS, 0.3, "g")
            outcomes.append("ok")
        except SpendCapError:
            outcomes.append("capped")

    threads = [threading.Thread(target=attempt) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("ok") == 3 and Ledger(path).spent() == pytest.approx(0.9)


def test_separate_processes_cannot_overshoot(tmp_path):
    path = tmp_path / "l.jsonl"
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from symbiont.egress.spend import Ledger, SpendCapError, SpendCaps\n"
        "try:\n"
        "    Ledger(Path(sys.argv[1])).reserve('run', SpendCaps(1.0, None), 0.3, 'g')\n"
        "    print('ok')\n"
        "except SpendCapError:\n"
        "    print('capped')\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path)], stdout=subprocess.PIPE, text=True
        )
        for _ in range(8)
    ]
    results = [proc.communicate()[0].strip() for proc in procs]
    assert results.count("ok") == 3 and Ledger(path).spent() == pytest.approx(0.9)
