"""Retry rule and results-file sections of the offline-selection run script."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "offline" / "run_selection.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("run_selection", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def flaky(failures, message="HTTP 429 Too Many Requests"):
    calls = []

    def call():
        calls.append(1)
        if len(calls) <= failures:
            raise RuntimeError(message)
        return "rows"

    return call, calls


def test_backoff_retries_a_429_then_succeeds(script):
    waits = []
    call, calls = flaky(2)
    assert script.with_backoff(call, sleep=waits.append) == "rows"
    assert waits == list(script.BACKOFF_SECONDS[:2]) and len(calls) == 3


def test_backoff_gives_up_with_a_clear_message(script):
    call, _ = flaky(99)
    with pytest.raises(script.RateLimitedError, match="429"):
        script.with_backoff(call, sleep=lambda _wait: None)


def test_backoff_does_not_retry_other_errors(script):
    call, calls = flaky(99, message="connection refused")
    with pytest.raises(RuntimeError, match="refused"):
        script.with_backoff(call, sleep=lambda _wait: pytest.fail("slept"))
    assert len(calls) == 1


def test_results_document_keeps_the_prereg_section_order(script):
    from argparse import Namespace

    from symbiont.eval.offline import OfflineScores, SessionScores
    from symbiont.eval.offline_verdict import Verdict
    from symbiont.eval.selection_record import Calibration, FinalScores, HubCheckout

    session = SessionScores("t0", (True, False), (True, False), (False, False), (None, None))
    arm = OfflineScores("x", (session,))
    thresholds = script.sel.MUSHROOM_THRESHOLDS
    cal = Calibration(
        {1: 0.5},
        1,
        {("mushroom", seed, thr): 0.5 for seed in script.sel.WIRING_SEEDS for thr in thresholds},
        dict.fromkeys(script.sel.WIRING_SEEDS, 0.5),
    )
    outcome = script.Outcome(
        HubCheckout("task", "2024-01-01", "abc", 3),
        cal,
        FinalScores(arm, arm, {0: arm}),
        Verdict("counters", 0.0, -0.1, 0.1),
        "table",
        {"records": 2},
        (frozenset({"a"}), frozenset({"b"})),
        {"mushroom_final_s": 1.0},
    )
    args = Namespace(smoke_train_only=True, workers=2)
    label = {
        "prereg": None,
        "freeze_commit": None,
        "prereg_sha256": None,
        "run_label": "exploratory",
    }
    doc = script.results_document(args, outcome, 0.0, label)
    assert list(doc)[:3] == ["smoke", "prereg", "freeze_commit"]
    assert list(doc)[-3:] == ["table_markdown", "g6", "per_step"]
    assert doc["smoke"] is True and doc["data"]["tasks_train"] == 1


def test_scored_without_a_prereg_refuses_before_any_work(script):
    from symbiont.eval.prereg import PreregNotFrozenError

    with pytest.raises(PreregNotFrozenError, match="--scored needs --prereg"):
        script.main(["run", "--data", "d", "--meta", "m", "--out", "o", "--scored"])


def test_scored_smoke_is_refused(script):
    with pytest.raises(SystemExit):
        script.main(
            ["run", "--data", "d", "--meta", "m", "--out", "o", "--scored", "--smoke-train-only"]
        )
