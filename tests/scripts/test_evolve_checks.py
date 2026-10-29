"""The fitness check: gaming policies must stay below the empty card; the results file is labels."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import check_fitness  # noqa: E402 - needs the scripts path added above
import run_state  # noqa: E402

from symbiont.act1.game_fitness import Case, GameResult, Grade  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.periphery


def test_a_policy_at_or_above_the_empty_card_fails_the_check_naming_it():
    check_fitness.require_below(0.30, {"stand_still": 0.0, "fire_in_place": 0.0, "spin": 0.1})
    with pytest.raises(check_fitness.GamingBeatsEmptyError, match="spin 0.350"):
        check_fitness.require_below(0.30, {"stand_still": 0.0, "spin": 0.35})
    with pytest.raises(check_fitness.GamingBeatsEmptyError, match="stand_still"):
        check_fitness.require_below(0.30, {"stand_still": 0.30})


def game(card, level, share):
    case = Case(level, 5, 3, CutSetting.NONE)
    return GameResult(case, card, Grade.GRADED, False, share, 0, False, 0, 0, None)


def test_card_means_come_from_the_state_file_on_the_given_cases_only():
    cases = [Case("MAP01", 5, 3, CutSetting.NONE), Case("MAP02", 5, 3, CutSetting.NONE)]
    stored = {}
    for card, level, share in (("a", "MAP01", 0.4), ("a", "MAP02", 0.8), ("a", "MAP05", 1.0)):
        result = game(card, level, share)
        stored[run_state.game_key(card, result.case)] = run_state.result_to_json(result)
    means = check_fitness.card_means(stored, cases)
    assert means == {"a": pytest.approx(0.3)}


def test_the_results_document_labels_floors_and_references_and_passes_the_content_gate(tmp_path):
    noise = {"verdict": "select", "within_variance": 0.01, "between_variance": 0.02}
    document = check_fitness.results_document(
        0.3, {"stand_still": 0.0, "spin": 0.05}, {"e3b0": 0.3, "ab12": 0.5}, noise
    )
    assert [(row["label"], row["role"]) for row in document["rows"]] == [
        ("empty card", "reference"), ("stand_still", "floor"), ("spin", "floor")
    ]  # fmt: skip
    assert document["fitness_spread"] == pytest.approx(0.2)
    target = tmp_path / "results" / "evolve-gen0.json"
    target.parent.mkdir()
    target.write_text(json.dumps(document))
    gate = ROOT / "scripts" / "gates" / "check_results_content.py"
    done = subprocess.run(
        [sys.executable, str(gate), str(target)], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr
