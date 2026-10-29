"""The card-sensitivity check: fresh shared cases, honest cards, and the arithmetic."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import card_sensitivity as cs  # noqa: E402 - needs the scripts path added above

from symbiont.act1.evolve_split import FINAL_SEEDS, GENERATION_SEED_BASE, VALIDATION_SEED_BASE  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade  # noqa: E402
from symbiont.act1.generality import check_card  # noqa: E402
from symbiont.act1.levels import require_training  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402

pytestmark = pytest.mark.periphery


def test_twelve_shared_cases_on_two_training_levels_with_seeds_no_evolution_run_used():
    cases = cs.sensitivity_cases()
    assert len(cases) == 12 and len({(c.level, c.seed) for c in cases}) == 12
    for case in cases:
        require_training(case.level)
        assert case.seed not in FINAL_SEEDS
        assert (
            case.seed > VALIDATION_SEED_BASE + 100 * 1_000
            and case.seed > GENERATION_SEED_BASE + 100 * 1_000
        )


def test_the_hand_written_cards_obey_the_caps_and_pass_the_pattern_filter():
    for card in (cs.BAD_CARD, cs.STRONG_CARD):
        assert all(v.general for v in check_card(card))
    assert cs.BAD_CARD.card_id != cs.STRONG_CARD.card_id


def test_the_four_settings_differ_in_exactly_what_the_check_says():
    a, b, c, d = (cs.SPECS[s] for s in (cs.Setting.A, cs.Setting.B, cs.Setting.C, cs.Setting.D))
    assert (a.effort.value, a.temperature, a.placement.value) == ("low", None, "prompt_prefix")
    assert b.temperature == 0.0 and b.effort == a.effort and b.placement == a.placement
    assert c.effort.value == "medium" and c.temperature is None and c.placement == a.placement
    assert d.placement.value == "system_rules" and d.effort == a.effort
    assert sum(spec.run_cap for spec in cs.SPECS.values()) <= 1.5


def game(share, mistakes=0, grade=Grade.GRADED):
    case = Case("MAP01", 1, 3, CutSetting.NONE)
    return GameResult(case, "x", grade, False, share, mistakes, False, 0, 0, None)


def test_cell_stats_use_the_graded_games_only():
    stats = cs.cell_stats([game(0.2), game(0.6), game(0.0, grade=Grade.UNGRADED)])
    assert stats["games"] == 2 and stats["ungraded"] == 1
    assert stats["mean"] == pytest.approx(0.2) and stats["sd"] == pytest.approx(0.1414, abs=1e-3)


def test_games_needed_follows_the_two_sample_formula_and_none_for_no_gap():
    # sd 0.2, gap 0.1: 15.68 * (0.2 / 0.1) ** 2 = 62.7
    assert cs.games_needed(0.2, 0.1) == 63
    assert cs.games_needed(0.2, 0.0) is None
    assert cs.games_needed(0.2, -0.2) == cs.games_needed(0.2, 0.2)


def test_the_setting_report_gives_gaps_in_sd_units_against_the_empty_card():
    def cell(mean, sd):
        return {"games": 12, "ungraded": 0, "mean": mean, "sd": sd}

    cells = {
        "empty": cell(-0.3, 0.2),
        "best_gen0": cell(-0.2, 0.2),
        "bad": cell(-0.6, 0.2),
        "strong": cell(-0.1, 0.2),
    }
    report = cs.setting_report(cells)
    assert report["pooled_sd"] == pytest.approx(0.2)
    assert report["gaps"]["bad"]["gap_in_sd"] == pytest.approx(-1.5)
    assert report["gaps"]["strong"]["gap_in_sd"] == pytest.approx(1.0)
    assert report["gaps"]["strong"]["games_per_card_needed"] == cs.games_needed(0.2, 0.2)


def test_the_best_generation_0_card_is_found_by_id_and_an_unknown_id_raises():
    state = {"seed_cards": [cs.STRONG_CARD.to_json(), cs.BAD_CARD.to_json()]}
    assert cs.best_gen0_card(state, cs.BAD_CARD.card_id) == cs.BAD_CARD
    with pytest.raises(KeyError):
        cs.best_gen0_card(state, "nope")


def test_only_the_medium_setting_asks_for_more_than_the_default_reply_tokens():
    from symbiont.egress.spark import DEFAULT_MAX_TOKENS

    assert cs.SPECS[cs.Setting.C].max_tokens == cs.MEDIUM_TOKENS > DEFAULT_MAX_TOKENS
    assert all(
        cs.SPECS[s].max_tokens == DEFAULT_MAX_TOKENS
        for s in (cs.Setting.A, cs.Setting.B, cs.Setting.D)
    )


def test_each_settings_players_carry_exactly_that_settings_fields():
    from symbiont.egress.spark import DEFAULT_MAX_TOKENS

    for setting, spec in cs.SPECS.items():
        players = cs.players_for(setting)
        assert (players.effort, players.temperature, players.placement) == (
            spec.effort, spec.temperature, spec.placement,
        )  # fmt: skip
        assert isinstance(players.max_tokens, int) and players.max_tokens >= DEFAULT_MAX_TOKENS
        assert players.run == f"sens-{setting.value}" and players.run_cap == spec.run_cap
    assert cs.players_for(cs.Setting.C).max_tokens == cs.MEDIUM_TOKENS
    assert cs.players_for(cs.Setting.B).temperature == 0.0
