"""Run 2's rules: fresh cases everywhere, a coin that ignores scores, paired intervals."""

import random
import re

import pytest

from symbiont.act1 import duel
from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.evolve_split import EvolveSplit, SmokeResult
from symbiont.act1.game_fitness import Case, GameResult, Grade
from symbiont.act1.generation import ParentChoice
from symbiont.act1.levels import LevelSplit, levels_in
from symbiont.act1.move_cuts import CutSetting

NAVIGABLE = (
    "MAP01",
    "MAP02",
    "MAP05",
    "MAP06",
    "MAP09",
    "MAP10",
    "MAP11",
    "MAP14",
    "MAP29",
    "MAP31",
)


def split():
    smoke = {
        level: SmokeResult(level in NAVIGABLE or level not in levels_in(LevelSplit.TRAINING), "")
        for level in levels_in(LevelSplit.TRAINING) + levels_in(LevelSplit.HELD_OUT)
    }
    return EvolveSplit.of(smoke)


def all_cases(seed=1):
    selection, held_back = duel.final_cases(split(), seed)
    cases = [*duel.noise_cases(split(), seed), *selection, *held_back]
    for generation in range(1, duel.GENERATIONS + 1):
        cases.extend(duel.generation_cases(split(), generation, seed))
    return cases


def test_no_level_and_seed_is_used_twice_across_noise_generations_and_the_final_test():
    cases = all_cases()
    pairs = [(c.level, c.seed) for c in cases]
    assert len(pairs) == len(set(pairs)) == 5 + 24 + 25  # noise + final + 5 generations x 5


def test_the_game_budget_matches_the_design():
    assert duel.NOISE_CASES * duel.NOISE_REPLICATES == 25
    assert 2 * duel.CASES_PER_GENERATION * duel.GENERATIONS == 50  # per arm, 100 for both
    assert 3 * (duel.FINAL_SELECTION_CASES + duel.FINAL_VALIDATION_CASES) == 72


def test_selection_cases_use_selection_maps_and_held_back_cases_use_validation_maps_only():
    sp = split()
    selection, held_back = duel.final_cases(sp, 1)
    assert {c.level for c in selection} <= set(sp.selection)
    assert {c.level for c in held_back} == set(sp.validation)
    for case in [*duel.noise_cases(sp, 1), *selection]:
        assert case.level in sp.selection
    held_out = set(levels_in(LevelSplit.HELD_OUT))
    assert held_out.isdisjoint({c.level for c in all_cases()})


def test_a_generation_has_five_distinct_maps_and_the_same_cases_for_the_same_seed():
    sp = split()
    cases = duel.generation_cases(sp, 2, 1)
    assert len({c.level for c in cases}) == 5
    assert cases == duel.generation_cases(sp, 2, 1)
    assert cases != duel.generation_cases(sp, 3, 1)


def game(share, level="MAP01", seed=1, mistakes=0, pains=()):
    case = Case(level, seed, 3, CutSetting.NONE)
    return GameResult(case, "x", Grade.GRADED, False, share, mistakes, False, 0, 0, None, pains)


def test_best_and_worst_are_by_fitness_and_need_two_graded_games():
    games = [game(0.3, seed=1), game(0.9, seed=2), game(0.0, seed=3)]
    best, worst = duel.best_and_worst(games)
    assert (best.case.seed, worst.case.seed) == (2, 3)
    with pytest.raises(duel.NotEnoughGamesError):
        duel.best_and_worst([game(0.3)])


def test_the_compare_text_tells_both_games_in_prose_without_a_map_or_a_number_with_a_point():
    text = duel.compare_text(
        [game(0.9, seed=2, pains=(("wall_bump", 1),), mistakes=1), game(0.0, seed=3)]
    )
    assert text.startswith("BEST GAME: ") and " WORST GAME: " in text
    assert "MAP" not in text and "." in text
    assert not re.search(r"\d\.\d", text)


def card(n):
    return Card.of([Lesson(f"wrong {n}", f"instead {n}", f"check {n}")])


def test_the_selecting_arm_keeps_the_better_card_and_a_tie_goes_to_the_shorter_one():
    a, b = card(1), card(2)
    coin = random.Random(0)
    assert duel.pick_survivor((a, [0.1, 0.2]), (b, [0.5, 0.5]), ParentChoice.LEXICASE, coin) == b
    assert duel.pick_survivor((a, [0.5, 0.5]), (b, [0.1, 0.2]), ParentChoice.LEXICASE, coin) == a
    shorter = Card.of([Lesson("w", "i", "c")])
    longer = Card.of([Lesson("a long wrong", "a long instead", "a long check")])
    assert (
        duel.pick_survivor((longer, [0.3]), (shorter, [0.3]), ParentChoice.LEXICASE, coin)
        == shorter
    )


def test_the_controls_coin_ignores_the_scores():
    a, b = card(1), card(2)

    def picks(current_scores, child_scores):
        return [
            duel.pick_survivor(
                (a, current_scores), (b, child_scores), ParentChoice.RANDOM, random.Random(seed)
            )
            for seed in range(40)
        ]

    assert picks([0.0], [1.0]) == picks([1.0], [0.0])  # same coin, whatever the scores
    assert {c.card_id for c in picks([0.0], [1.0])} == {a.card_id, b.card_id}


def test_replay_noise_is_the_pooled_variance_of_a_game_replayed_on_the_same_case():
    replicates = [[0.0, 1.0], [0.2, 1.2], [0.4, 0.8]]  # 3 replicates of 2 cases
    stats = duel.replay_noise(replicates)
    # each case's three values spread by 0.2, so each variance is 0.04
    assert stats["replay_variance"] == pytest.approx(0.04)
    assert stats["replay_sd"] == pytest.approx(0.2)
    assert (stats["cases"], stats["replicates"]) == (2.0, 3.0)


def test_the_expected_half_width_is_1_96_standard_errors_of_a_difference_of_two_single_games():
    assert duel.expected_half_width(0.04, 24) == pytest.approx(1.96 * (2 * 0.04 / 24) ** 0.5)


def test_paired_groups_pair_by_case_and_group_by_map():
    c1, c2 = Case("MAP01", 1, 3, CutSetting.NONE), Case("MAP02", 2, 3, CutSetting.NONE)
    scores = {"evolved": {c1: 0.5, c2: 0.2}, "control": {c1: 0.1, c2: 0.3}}
    groups = duel.paired_groups(scores, "evolved", "control")
    assert groups == {"MAP01": [pytest.approx(0.4)], "MAP02": [pytest.approx(-0.1)]}


def test_the_interval_excludes_zero_for_a_clear_gain_and_covers_it_for_noise():
    clear = {f"MAP{n:02d}": [0.5, 0.4] for n in range(1, 9)}
    low, high = duel.paired_interval(clear, seed=1)
    assert low > 0 and duel.decision_word(low, high) == "better"
    noisy = {f"MAP{n:02d}": [(-1) ** n * 0.5] for n in range(1, 9)}
    low, high = duel.paired_interval(noisy, seed=1)
    assert low < 0 < high and duel.decision_word(low, high) == "tie"
    assert duel.decision_word(-0.5, -0.1) == "worse"


def test_the_interval_is_reproducible_from_its_seed():
    groups = {"MAP01": [0.1, 0.3], "MAP02": [-0.2], "MAP05": [0.4, 0.1]}
    assert duel.paired_interval(groups, seed=3) == duel.paired_interval(groups, seed=3)


def test_a_child_beats_its_parent_only_with_a_strictly_higher_mean():
    assert duel.beats_parent([0.2, 0.4], [0.1, 0.4])
    assert not duel.beats_parent([0.3], [0.3])
    assert not duel.beats_parent([0.1], [0.3])


def test_the_wilson_interval_brackets_the_share_and_stays_within_zero_and_one():
    share, low, high = duel.wilson_interval(3, 5)
    assert share == 0.6 and 0.2 < low < 0.6 < high < 0.95
    assert duel.wilson_interval(0, 5)[1] == 0.0 and duel.wilson_interval(5, 5)[2] == 1.0
    with pytest.raises(duel.NotEnoughGamesError):
        duel.wilson_interval(0, 0)


def test_child_share_counts_wins_and_the_mean_gain():
    rows = [
        {"child_mean": 0.5, "current_mean": 0.1},
        {"child_mean": 0.2, "current_mean": 0.3},
        {"child_mean": 0.4, "current_mean": 0.4},
    ]
    stats = duel.child_share(rows)
    assert stats["beat_parent"] == 1.0 and stats["children"] == 3.0
    assert stats["mean_gain"] == pytest.approx((0.4 - 0.1 + 0.0) / 3)


def test_run_three_is_sized_for_about_five_hundred_and_sixty_games_on_fresh_cases():
    plan = duel.RUN3
    per_arm = plan.generations * (1 + plan.children_per_generation) * plan.cases_per_generation
    random_children = plan.generations * plan.children_per_generation * plan.cases_per_generation
    final = 3 * (plan.final_selection_cases + plan.final_validation_cases)
    assert (per_arm, random_children, final) == (160, 120, 120)
    assert 2 * per_arm + random_children + final == 560


def test_run_three_cases_never_meet_run_two_cases_or_each_other():
    sp = split()
    seen = set()
    for plan in (duel.RUN2, duel.RUN3):
        selection, held_back = duel.final_cases(sp, 1, plan)
        cases = [*duel.noise_cases(sp, 1, plan), *selection, *held_back]
        for generation in range(1, plan.generations + 1):
            cases += duel.generation_cases(sp, generation, 1, plan)
        pairs = [(c.level, c.seed) for c in cases]
        assert len(pairs) == len(set(pairs)) and seen.isdisjoint(pairs)
        seen |= set(pairs)


def test_more_cases_than_maps_cycle_through_shuffled_rounds_of_all_the_maps():
    sp = split()
    cases = duel.generation_cases(sp, 1, 1, duel.RUN3)
    assert len(cases) == 10 and len({c.seed for c in cases}) == 10
    assert set(c.level for c in cases) <= set(sp.selection)
    counts = {level: sum(c.level == level for c in cases) for level in sp.selection}
    assert max(counts.values()) - min(counts.values()) <= 1 and min(counts.values()) >= 1


def test_run_two_cases_are_unchanged_by_the_plan_parameter():
    sp = split()
    assert duel.generation_cases(sp, 2, 1) == duel.generation_cases(sp, 2, 1, duel.RUN2)
    assert len(duel.generation_cases(sp, 2, 1)) == 5


def test_pick_among_several_keeps_the_best_mean_or_a_blind_coins_choice():
    cards = [card(n) for n in range(4)]
    scored = [(cards[0], [0.1]), (cards[1], [0.5]), (cards[2], [0.3]), (cards[3], [0.2])]
    assert duel.pick_among(scored, ParentChoice.LEXICASE, random.Random(0)) == cards[1]
    reversed_scores = [(c, [1.0 - s[0]]) for c, s in scored]
    first = [duel.pick_among(scored, ParentChoice.RANDOM, random.Random(i)) for i in range(30)]
    again = [
        duel.pick_among(reversed_scores, ParentChoice.RANDOM, random.Random(i)) for i in range(30)
    ]
    assert first == again and len(set(first)) > 1
