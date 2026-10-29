"""The cap check reads a small running total, not the whole ledger, and the two must agree."""

import json
import threading

import pytest

from symbiont.egress.spend import (
    Ledger,
    LedgerEntry,
    LedgerMismatchError,
    SpendCaps,
    Tier,
    Usage,
)

CAPS = SpendCaps(total_usd=1000.0, run_usd=None)


def settled(cost, run="run"):
    usage = Usage(prompt=100, cached=0, completion=10, reasoning=0)
    return LedgerEntry(run, "g", "m", Tier.CONTRIBUTOR, usage, cost, 1.0)


def sidecar(path):
    return json.loads((path.with_name(path.name + ".total.json")).read_text())


def test_after_the_first_call_the_ledger_file_is_never_scanned_again(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.settle(ledger.reserve("run", CAPS, 0.5, "a"), settled(0.1))

    def forbidden():
        raise AssertionError("the cap check re-read the whole ledger")

    monkeypatch.setattr(ledger, "entries", forbidden)
    call = ledger.reserve("run", CAPS, 0.2, "b")
    assert ledger.spent() == pytest.approx(0.3) and ledger.spent("run") == pytest.approx(0.3)
    ledger.settle(call, settled(0.05))
    ledger.release(ledger.reserve("run", CAPS, 0.4, "c"))
    assert ledger.spent() == pytest.approx(0.15)


def test_the_running_total_matches_a_full_scan_after_concurrent_use(tmp_path):
    path = tmp_path / "l.jsonl"

    def worker(index):
        ledger = Ledger(path)
        for n in range(5):
            call = ledger.reserve(f"run{index % 2}", CAPS, 0.01, "g")
            if n % 2:
                ledger.settle(call, settled(0.004, f"run{index % 2}"))
            else:
                ledger.release(call)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    scanned = sum(row["cost_usd"] for row in Ledger(path).entries())
    assert sidecar(path)["total"] == pytest.approx(scanned) == pytest.approx(6 * 2 * 0.004)
    Ledger(path).spent()  # a fresh start validates sidecar against the scan without raising


def test_a_crash_between_reserve_and_settle_leaves_the_reservation_counted(tmp_path):
    path = tmp_path / "l.jsonl"
    Ledger(path).reserve("run", CAPS, 0.5, "g")  # the process dies here
    restarted = Ledger(path)
    assert restarted.spent() == pytest.approx(0.5)
    assert len(sidecar(path)["open"]) == 1


def test_a_start_up_where_sidecar_and_ledger_disagree_raises(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.settle(ledger.reserve("run", CAPS, 0.5, "g"), settled(0.1))
    total = path.with_name(path.name + ".total.json")
    state = json.loads(total.read_text())
    state["total"] = 0.0  # someone edited it, or a crash lost an update
    total.write_text(json.dumps(state))
    with pytest.raises(LedgerMismatchError, match="rebuild_total"):
        Ledger(path).spent()


def test_a_crash_after_the_ledger_line_but_before_the_total_is_caught_at_restart(
    tmp_path, monkeypatch
):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.reserve("run", CAPS, 0.2, "ok")

    def crash(state):
        raise OSError("power cut")

    monkeypatch.setattr(ledger, "_save_state", crash)
    with pytest.raises(OSError, match="power cut"):
        ledger.reserve("run", CAPS, 0.3, "lost")
    with pytest.raises(LedgerMismatchError):
        Ledger(path).spent()


def test_rebuild_total_repairs_the_sidecar_from_the_ledger(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.settle(ledger.reserve("run", CAPS, 0.5, "g"), settled(0.1))
    path.with_name(path.name + ".total.json").write_text('{"total": 9, "runs": {}, "open": {}}')
    repaired = Ledger(path)
    repaired.rebuild_total()
    assert repaired.spent() == pytest.approx(0.1)
    assert Ledger(path).spent() == pytest.approx(0.1)


def test_an_existing_ledger_without_a_sidecar_gets_one_from_the_scan(tmp_path):
    path = tmp_path / "l.jsonl"
    old = {"run": "a", "cost_usd": 0.25, "label": "g"}  # a line from before reservations existed
    path.write_text(json.dumps(old) + "\n")
    assert Ledger(path).spent("a") == pytest.approx(0.25)
    assert sidecar(path)["total"] == pytest.approx(0.25)
