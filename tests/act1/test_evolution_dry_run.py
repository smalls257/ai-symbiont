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


def control_parent_ranks(record):
    """For each generation, the fitness rank (0 = best) of the first parent of each child."""
    ranks = {}
    for generation in range(1, record.last_played + 1):
        table = record.tables[Arm.NO_SELECTION][generation - 1]
        order = sorted(
            table.cards,
            key=lambda cid: -sum(table.scores[(cid, case)] for case in table.cases),
        )
        ranks[generation] = [
            order.index(b.parents[0])
            for b in record.births
            if b.arm == Arm.NO_SELECTION
            and b.generation == generation
            and b.operator.value not in ("elite", "seed_empty")
            and b.parents
            and b.parents[0] in order
        ]
    return ranks


def test_the_control_arms_parent_choices_differ_across_generations_and_ignore_fitness_rank():
    pooled = []
    for seed in range(8):
        ranks = control_parent_ranks(run(seed=seed, generations=6))
        firsts = [r[0] for r in ranks.values() if r]
        assert len(set(firsts)) > 1, (seed, firsts)  # not the same position every generation
        pooled.extend(rank for r in ranks.values() for rank in r)
    mean_rank = sum(pooled) / len(pooled)
    assert 1.5 < mean_rank < 3.5, mean_rank  # a random pick of six cards averages 2.5


def test_the_chance_source_of_a_generation_does_not_depend_on_the_other_generations():
    first = run(generations=3)
    longer = run(generations=5)
    early = [b for b in longer.births if b.generation <= 3]
    assert [b for b in first.births if b.generation <= 3] == early


def test_the_same_seed_gives_identical_output_twice():
    one, two = run(seed=4, generations=4), run(seed=4, generations=4)
    assert one.births == two.births and one.picks == two.picks and one.gaps == two.gaps
    assert [t.scores for t in one.tables[Arm.EVOLVED]] == [
        t.scores for t in two.tables[Arm.EVOLVED]
    ]


def test_the_authors_state_is_not_reset_between_generations():
    from symbiont.act1.offline_author import OfflineAuthor as Author

    author = Author()
    calls = []

    class Spy(Author):
        def vary(self, operator, parents, summary):
            calls.append(self.calls)
            return super().vary(operator, parents, summary)

    spy = Spy()
    from evolve_world import VariationTools as Tools

    record = evolve(
        seeds(),
        SPLIT,
        FakePlayer(),
        Tools(spy, tools().judge, tools().rng, tools().schedule, {}),
        RunRules(3, 1, 1, SpendRoom(10.0, 1.0)),
    )
    assert record.last_played == 3 and author.calls == 0
    assert calls == sorted(calls) and len(set(calls)) == len(calls)  # one counter, never reset
