"""The whole loop with a fake player, author and judge: no engine, no model, no network."""

import time

import pytest

from evolve_world import HELD_OUT, SPLIT, FakePlayer, doors, run, seeds, tools
from symbiont.act1.evolution import RunRules, evolve
from symbiont.act1.lineage import Arm
from symbiont.act1.run_guards import GapWatch, NoiseVerdict, SpendRoom, TooManyUngradedError


def test_a_three_generation_run_finishes_with_both_arms_and_picks_for_each():
    record = run()
    assert record.stop_reason is None and record.last_played == 3 and record.last_good == 3
    assert set(record.picks) == {Arm.EVOLVED, Arm.NO_SELECTION}
    assert len(record.tables[Arm.EVOLVED]) == len(record.tables[Arm.NO_SELECTION]) == 4
    assert len(record.gaps) == 3
    assert record.noise is not None and record.noise.verdict is NoiseVerdict.SELECT


def test_the_whole_loop_runs_in_under_two_seconds():
    started = time.perf_counter()
    run()
    assert time.perf_counter() - started < 2.0


def test_selection_beats_chance_on_the_hidden_rule_in_most_seeds():
    wins = losses = 0
    for seed in range(20):
        record = run(seed=seed, generations=4)
        evolved, control = (
            doors(record.cards[record.picks[arm]]) for arm in (Arm.EVOLVED, Arm.NO_SELECTION)
        )
        wins += evolved > control
        losses += evolved < control
    assert wins > losses, (wins, losses)


def test_no_held_out_level_is_ever_played():
    player = FakePlayer()
    run(player)
    assert HELD_OUT.isdisjoint(player.levels)
    assert set(player.levels) <= set(SPLIT.selection) | set(SPLIT.validation)


def test_validation_games_are_never_in_the_games_picking_reads():
    record = run()
    assert {g.role.value for g in record.games} == {"selection"}
    assert {g.role.value for g in record.validation_games} == {"validation"}
    assert all(g.result.case.level in SPLIT.validation for g in record.validation_games)


def test_injected_ungraded_games_raise_in_the_generation_they_hit():
    with pytest.raises(TooManyUngradedError):
        run(FakePlayer(ungraded_every=7))


def test_a_widening_gap_stops_at_the_right_generation_and_picks_from_the_last_good_one():
    record = run(FakePlayer(validation_drop=0.15), generations=6)
    assert record.stop_reason is not None and record.stop_reason.startswith("gap")
    watch = GapWatch(record.noise.standard_error)
    for generation, training, validation in record.gaps:
        watch.record(generation, training, validation)
    expected = watch.verdict().last_good_generation
    assert record.last_good == expected < record.last_played < 6
    picked_games = [
        g for g in record.games if g.result.card_id == record.picks[Arm.EVOLVED]
        and g.generation in (expected - 1, expected)
    ]  # fmt: skip
    assert len(picked_games) >= 8


def test_a_noisy_player_doubles_the_games_per_case():
    record = run(FakePlayer(noise=0.4, effect=0.0), generations=1)
    assert record.noise.verdict is NoiseVerdict.DOUBLE_GAMES
    assert record.games_per_case == 2
    assert len({g.result.case for g in record.games if g.generation == 1}) == 8


def test_a_noisy_player_with_no_money_left_stops_before_generation_one():
    rules = RunRules(3, 1, 1, SpendRoom(remaining_usd=0.5, doubling_cost_usd=1.0))
    record = evolve(seeds(), SPLIT, FakePlayer(noise=0.4, effect=0.0), tools(), rules)
    assert record.noise.verdict is NoiseVerdict.STOP
    assert record.stop_reason.startswith("noise") and record.last_played == 0 and record.picks == {}


def test_the_births_make_a_lineage_that_walks_back_to_generation_zero():
    from symbiont.act1.lineage import Birth, Lineage, Operator

    record = run()
    lineage = Lineage()
    for card in seeds():
        lineage.add(Birth(card.card_id, 0, Arm.EVOLVED, Operator.SEED_HISTORY, (), "seed", None))
    for birth in record.births:
        if birth.arm == Arm.EVOLVED:
            lineage.add(birth)
    assert lineage.ancestors(record.picks[Arm.EVOLVED])[-1].generation == 0
