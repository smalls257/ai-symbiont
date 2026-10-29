"""The T49 runner applies the frozen bar, writes the verdict first and refuses unregistered runs."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "offline"


@pytest.fixture(scope="module")
def script():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import run_text_ceiling
        import text_ceiling_score
    finally:
        sys.path.remove(str(SCRIPTS))
    return run_text_ceiling, text_ceiling_score


def gap(value, low):
    return {"value": value, "ci95_low": low, "ci95_high": value + 0.1, "undefined_draws": 0}


def test_the_bar_passes_only_when_all_three_parts_hold(script):
    _, ts = script
    assert ts.verdict(gap(0.03, 0.001), 0.03)["verdict"] == "PASS"
    assert ts.verdict(gap(0.029, 0.01), 0.05)["verdict"] == "FAIL"
    assert ts.verdict(gap(0.05, 0.0), 0.05)["verdict"] == "FAIL"
    assert ts.verdict(gap(0.05, None), 0.05)["verdict"] == "FAIL"
    assert ts.verdict(gap(0.05, 0.01), 0.029)["verdict"] == "FAIL"


def test_a_failed_bar_carries_the_registered_headline(script):
    _, ts = script
    found = ts.verdict(gap(0.0, -0.1), 0.0)
    assert found["result"] == (
        "the step text does not raise the ceiling enough to justify more learner tuning"
    )
    assert found["bar_parts"] == {
        "net_gain_at_least_0.03": False,
        "net_gain_ci95_low_above_0": False,
        "auc_gain_at_least_0.03": False,
    }


def test_the_headline_gap_is_the_candidate_against_the_reference(script):
    _, ts = script
    wanted = {"option": ts.HEADLINE, "what": "MLP old+text minus logistic old", "value": 1}
    other = {"option": ts.HEADLINE, "what": "MLP old minus logistic old", "value": 2}
    assert ts.headline_gap([{"differences": [other, wanted]}]) == wanted
    with pytest.raises(ValueError, match="expected one"):
        ts.headline_gap([{"differences": [other]}])


def test_the_results_file_opens_with_the_verdict_word(script, tmp_path):
    runner, _ = script
    out = tmp_path / "r.json"
    runner.write_verdict_first(out, {"run_label": "scored", "verdict": "FAIL", "rows": [1, 2]})
    first = out.read_text().splitlines()[0]
    assert "FAIL" in first
    assert json.loads(out.read_text()) == {"verdict": "FAIL", "run_label": "scored", "rows": [1, 2]}


def test_a_frozen_run_on_reused_data_is_labelled_as_the_prereg_says_never_scored(script):
    runner, _ = script
    assert runner.frozen_run_label("scored") == "gate on re-used data, not a scored claim"
    assert runner.frozen_run_label("exploratory") == "exploratory"


def test_the_committed_t49_result_never_calls_itself_scored():
    result = json.loads((SCRIPTS.parents[1] / "results" / "text-ceiling.json").read_text())
    assert result["run_label"] == result["data_label"] == "gate on re-used data, not a scored claim"


def test_the_table_line_shows_an_undefined_metric_as_n_a_instead_of_crashing(script):
    _, ts = script
    undefined = {"value": None, "ci95_low": None, "ci95_high": None, "undefined_draws": 9}
    row = {"arm": "MLP old+text", "role": "under test"}
    row["metrics"] = {ts.NET: undefined, "precision": {"value": None}}
    line = ts.table_line(row, {"roc_auc": None, "precision_top_1pct": None})
    assert line.count("n/a") == 6


def run_main(runner, monkeypatch, *extra):
    argv = ["run", "--pool", "p", "--data-dir", "d", "--embeddings", "e", "--out", "o", *extra]
    monkeypatch.setattr(sys, "argv", argv)
    runner.main()


def test_scored_without_a_prereg_refuses_before_any_work(script, monkeypatch):
    from symbiont.eval.prereg import PreregNotFrozenError

    with pytest.raises(PreregNotFrozenError, match="--scored needs --prereg"):
        run_main(script[0], monkeypatch, "--scored")


def test_scored_with_another_runs_prereg_refuses(script, monkeypatch):
    from symbiont.eval.prereg import PreregNotFrozenError

    other = Path(__file__).resolve().parents[2] / "prereg" / "2026-10-29-offline-selection.md"
    with pytest.raises(PreregNotFrozenError):
        run_main(script[0], monkeypatch, "--scored", "--prereg", str(other))


def test_a_rehearsal_is_never_scored(script, monkeypatch):
    with pytest.raises(SystemExit, match="never a scored run"):
        run_main(script[0], monkeypatch, "--scored", "--rehearsal")
