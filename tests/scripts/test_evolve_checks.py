"""The fitness check: gaming policies must stay below the empty card; the results file is labels."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import check_fitness  # noqa: E402 - needs the scripts path added above
import check_noise  # noqa: E402, F401
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


POOL = ["MAP01", "MAP02", "MAP05", "MAP06", "MAP29"]


def stored_run(first_shares, second_shares, ungraded=()):
    """A state.json with 3 seed cards and their first- and second-seed games on generation 0."""
    from symbiont.act1.card_genome import Card, Lesson
    from symbiont.act1.evolve_split import EvolveSplit, generation_cases

    cards = [
        Card.of([]),
        Card.of([Lesson("a", "b", "c")]),
        Card.of([Lesson("d", "e", "f")]),
    ]
    blocks = generation_cases(EvolveSplit.exploratory(POOL), 0, 1, 2)
    games = {}
    for number, card in enumerate(cards):
        for index, case in enumerate(blocks):
            shares = first_shares if index < 4 else second_shares
            grade = Grade.UNGRADED if (number, index) in ungraded else Grade.GRADED
            result = GameResult(
                case, card.card_id, grade, False, shares[number][index % 4], 0, False, 0, 0, None
            )
            games[run_state.game_key(card.card_id, case)] = run_state.result_to_json(result)
    return {"seed_cards": [card.to_json() for card in cards], "games": games}


def test_the_noise_report_is_computed_from_the_stored_games_at_the_selection_size():

    # Every card scores 0.4 or 0.6 depending on the seed: luck, with no real difference.
    first = [[0.4, 0.4, 0.4, 0.4]] * 3
    second = [[0.6, 0.6, 0.6, 0.6]] * 3
    state = stored_run(first, second)
    report = check_noise.report_from_state(state, POOL, 1, 4)
    assert report.verdict.value == "double_games" and report.pairs_used == 12
    assert report.true_between_variance == 0.0 and report.games_needed is None


def test_a_level_with_an_ungraded_noise_game_is_left_out_and_counted_out():

    first = [[0.1, 0.2, 0.3, 0.4], [0.2, 0.3, 0.4, 0.5], [0.3, 0.4, 0.5, 0.6]]
    second = [[0.2, 0.3, 0.4, 0.5], [0.3, 0.4, 0.5, 0.6], [0.4, 0.5, 0.6, 0.7]]
    state = stored_run(first, second, ungraded={(1, 2)})  # card 1, first-block level 2
    report = check_noise.report_from_state(state, POOL, 1, 4)
    assert report.pairs_used == 9  # 3 cards x 3 levels


def test_stored_games_with_no_complete_level_raise():

    shares = [[0.1] * 4] * 3
    state = stored_run(shares, shares, ungraded={(0, 0), (0, 1), (0, 2), (0, 3)})
    with pytest.raises(check_noise.IncompleteNoiseGamesError):
        check_noise.report_from_state(state, POOL, 1, 4)


def test_gaming_means_can_be_reused_from_an_earlier_results_file(tmp_path):
    earlier = tmp_path / "gen0.json"
    earlier.write_text(
        json.dumps(
            {
                "rows": [
                    {"label": "empty card", "role": "reference", "mean_fitness": -0.3},
                    {"label": "spin", "role": "floor", "mean_fitness": -0.9},
                ]
            }
        )
    )
    assert check_fitness.reused_gaming(earlier) == {"spin": -0.9}
