"""The three-way split and the draws: reproducible, disjoint, and never the test condition."""

import pytest

from symbiont.act1.evolve_split import (
    EvolveSplit,
    MissingSmokeResultError,
    NotEnoughLevelsForExplorationError,
    NotSelectionLevelError,
    SmokeResult,
    condition_of,
    final_cases,
    generation_cases,
    validation_cases,
)
from symbiont.act1.levels import LevelSplit, levels_in
from symbiont.act1.move_cuts import CutSetting

EVERY_MAP = tuple(f"MAP{n:02d}" for n in range(1, 33))
PASS = SmokeResult(True, "")


def smoke(**failing):
    return {m: SmokeResult(False, failing[m]) if m in failing else PASS for m in EVERY_MAP}


def test_held_out_is_every_fourth_map_and_a_failure_is_dropped_with_its_reason():
    split = EvolveSplit.of(smoke(MAP12="no route"))
    assert split.held_out == tuple(f"MAP{n:02d}" for n in (4, 8, 16, 20, 24, 28, 32))
    assert split.dropped == {"MAP12": "no route"}


NAVIGABLE_TRAINING = (
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


def only_these_training_maps_pass(passing):
    """A smoke dict where just these training maps (and every held-out map) pass."""
    failing = {m: "no route" for m in levels_in(LevelSplit.TRAINING) if m not in passing}
    return smoke(**failing)


def test_four_validation_maps_are_spread_over_the_24_when_all_pass():
    split = EvolveSplit.of(smoke())
    assert split.validation == ("MAP05", "MAP13", "MAP21", "MAP29")


def test_the_ten_navigable_training_maps_give_three_validation_maps_and_seven_for_selection():
    split = EvolveSplit.of(only_these_training_maps_pass(NAVIGABLE_TRAINING))
    assert split.validation == ("MAP02", "MAP10", "MAP29")
    assert split.selection == ("MAP01", "MAP05", "MAP06", "MAP09", "MAP11", "MAP14", "MAP31")


def test_too_few_passing_training_maps_to_leave_four_for_selection_raise():
    with pytest.raises(NotEnoughLevelsForExplorationError, match="fewer than 4"):
        EvolveSplit.of(only_these_training_maps_pass(NAVIGABLE_TRAINING[:6]))


def test_selection_has_twenty_levels_and_no_overlap_with_the_other_two():
    split = EvolveSplit.of(smoke())
    assert len(split.selection) == 20
    assert set(split.selection).isdisjoint(split.validation)
    assert set(split.selection).isdisjoint(split.held_out)
    assert set(split.selection) | set(split.validation) == set(levels_in(LevelSplit.TRAINING))


def test_a_training_level_that_failed_the_smoke_test_is_not_in_selection():
    split = EvolveSplit.of(smoke(MAP02="crash"))
    assert "MAP02" not in split.selection and "MAP02" not in split.validation
    assert len(split.selection) == 20  # 23 pass: three validation maps


def test_a_missing_smoke_result_raises_instead_of_assuming_a_pass():
    partial = smoke()
    del partial["MAP20"]
    with pytest.raises(MissingSmokeResultError, match="MAP20"):
        EvolveSplit.of(partial)


def test_require_selection_refuses_validation_and_held_out_levels():
    split = EvolveSplit.of(smoke())
    split.require_selection("MAP01")
    for level in ("MAP05", "MAP08"):
        with pytest.raises(NotSelectionLevelError, match=level):
            split.require_selection(level)


def draws(split, generations=range(1, 7), run_seed=42, games_per_case=1):
    return [generation_cases(split, g, run_seed, games_per_case) for g in generations]


def test_each_generation_has_four_selection_levels_and_one_skill():
    split = EvolveSplit.of(smoke())
    for cases in draws(split):
        assert len(cases) == 4 and len({c.level for c in cases}) == 4
        assert all(c.level in split.selection for c in cases)
        assert len({(c.skill, c.cuts) for c in cases}) == 1
        assert cases[0].skill in (2, 3, 4)


def test_games_per_case_doubles_the_seeds_on_each_of_the_same_levels():
    split = EvolveSplit.of(smoke())
    one = generation_cases(split, 1, 42, 1)
    two = generation_cases(split, 1, 42, 2)
    assert len(two) == 8 and {c.level for c in two} == {c.level for c in one}


def test_a_level_and_seed_pair_is_never_repeated_across_generations():
    pairs = [(c.level, c.seed) for cases in draws(EvolveSplit.of(smoke())) for c in cases]
    assert len(pairs) == len(set(pairs)) == 24


def test_no_training_case_is_the_harder_condition_and_cuts_are_off_at_skill_four():
    split = EvolveSplit.of(smoke())
    seen = set()
    for seed in range(40):
        for cases in draws(split, run_seed=seed):
            for c in cases:
                seen.add((c.skill, c.cuts))
                assert not (c.skill == 4 and c.cuts != CutSetting.NONE)
    assert seen == {
        (2, CutSetting.TEN_PERCENT),
        (3, CutSetting.TEN_PERCENT),
        (4, CutSetting.NONE),
    }


def test_the_same_run_seed_gives_the_same_draws_and_another_seed_a_different_one():
    split = EvolveSplit.of(smoke())
    assert draws(split) == draws(split)
    assert draws(split) != draws(split, run_seed=43)


def test_training_seeds_stay_clear_of_the_final_test_seeds():
    split = EvolveSplit.of(smoke())
    seeds = {c.seed for cases in draws(split) for c in cases}
    seeds |= {c.seed for g in range(1, 7) for c in validation_cases(split, g, 42)}
    assert seeds.isdisjoint({1001, 1002})


def test_validation_cases_are_one_per_validation_level_in_the_generations_condition():
    split = EvolveSplit.of(smoke())
    train, valid = generation_cases(split, 3, 42, 1), validation_cases(split, 3, 42)
    assert [c.level for c in valid] == list(split.validation)
    assert {(c.skill, c.cuts) for c in valid} == {(train[0].skill, train[0].cuts)}
    assert {c.seed for c in valid}.isdisjoint({c.seed for c in train})


def test_final_cases_are_32_when_all_eight_held_out_levels_pass():
    cases = final_cases(EvolveSplit.of(smoke()))
    assert len(cases) == 32 and len(set(cases)) == 32
    assert {c.seed for c in cases} == {1001, 1002}
    assert {condition_of(c) for c in cases} == {"normal", "harder"}


def test_final_cases_use_normal_skill_three_and_harder_skill_four_with_cuts():
    for c in final_cases(EvolveSplit.of(smoke())):
        expected = (
            (3, CutSetting.NONE) if condition_of(c) == "normal" else (4, CutSetting.TEN_PERCENT)
        )
        assert (c.skill, c.cuts) == expected


def test_a_dropped_held_out_level_shrinks_the_final_test():
    assert len(final_cases(EvolveSplit.of(smoke(MAP08="no route")))) == 28


FIVE = ("MAP01", "MAP02", "MAP05", "MAP06", "MAP29")


def test_the_exploratory_split_uses_the_given_levels_for_both_roles_and_has_no_held_out():
    split = EvolveSplit.exploratory(FIVE)
    assert split.selection == split.validation == FIVE and split.held_out == ()


def test_the_exploratory_split_refuses_a_held_out_level_and_too_few_levels():
    with pytest.raises(Exception, match="MAP24"):
        EvolveSplit.exploratory([*FIVE, "MAP24"])
    with pytest.raises(NotEnoughLevelsForExplorationError):
        EvolveSplit.exploratory(FIVE[:3])


def test_exploratory_training_and_validation_seeds_never_meet():
    split = EvolveSplit.exploratory(FIVE)
    training = {c.seed for g in range(7) for c in generation_cases(split, g, 1, 2)}
    held_back = {c.seed for g in range(7) for c in validation_cases(split, g, 1)}
    assert training.isdisjoint(held_back)
    assert {1001, 1002}.isdisjoint(training | held_back)
    assert len(validation_cases(split, 1, 1)) == 5
