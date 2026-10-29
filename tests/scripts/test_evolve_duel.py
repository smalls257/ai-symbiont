"""Run 2's phases on a fake player and author: fresh cases, honest survivors, a journal."""

import sys
from pathlib import Path

import pytest

from evolve_world import FakePlayer, seeds

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import duel_phases as dp  # noqa: E402 - needs the scripts path added above
import duel_random as dr  # noqa: E402

from symbiont.act1 import duel  # noqa: E402
from symbiont.act1.card_genome import Card, Lesson  # noqa: E402
from symbiont.act1.evolve_split import EvolveSplit, SmokeResult  # noqa: E402
from symbiont.act1.game_fitness import fitness  # noqa: E402
from symbiont.act1.generality import Rejection, Verdict  # noqa: E402
from symbiont.act1.levels import LevelSplit, levels_in  # noqa: E402
from symbiont.act1.lineage import Arm, Operator  # noqa: E402
from symbiont.act1.offline_author import AllowAllJudge, OfflineAuthor  # noqa: E402
from symbiont.act1.run_guards import MutationPromptError  # noqa: E402

pytestmark = pytest.mark.periphery
NAVIGABLE = {
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
}
SPLIT = EvolveSplit.of(
    {
        level: SmokeResult(level in NAVIGABLE or level in levels_in(LevelSplit.HELD_OUT), "")
        for level in levels_in(LevelSplit.TRAINING) + levels_in(LevelSplit.HELD_OUT)
    }
)
START = seeds()[1]


class MemoryJournal:
    def __init__(self):
        self.stored = {}

    def load(self, arm, generation):
        return self.stored.get((arm, generation))

    def save(self, arm, generation, cards, births):
        self.stored[(arm, generation)] = (cards, births)


class SpyAuthor(OfflineAuthor):
    def __init__(self):
        super().__init__()
        self.asked = []

    def vary(self, operator, parents, summary, seed):
        self.asked.append((operator, summary))
        return super().vary(operator, parents, summary, seed)


def first_games(player):
    cases = duel.noise_cases(SPLIT, 1)
    played = dp.play_pairs(player, [(START, case) for case in cases])
    return [played[(START.card_id, case)] for case in cases]


def run_arm(arm, author=None, journal=None, player=None, judge=None):
    player = player or FakePlayer()
    setup = dp.ArmSetup(
        arm,
        SPLIT,
        1,
        player,
        author or SpyAuthor(),
        judge or AllowAllJudge(),
        journal or MemoryJournal(),
    )
    return dp.ArmRunner(setup).go(START, first_games(player))


def test_each_arm_plays_fifty_games_on_fresh_cases_and_two_cards_per_generation():
    for arm in (Arm.EVOLVED, Arm.NO_SELECTION):
        player = FakePlayer()
        run = run_arm(arm, player=player)
        assert len(run.rows) == 5 and all(row["games"] == 10 for row in run.rows)
        played_by_generation = {}
        for number in range(1, 6):
            for case in duel.generation_cases(SPLIT, number, 1):
                played_by_generation.setdefault((case.level, case.seed), number)
        assert len(played_by_generation) == 25  # no case is shared between generations


def test_every_child_is_written_from_the_best_and_worst_games_with_the_compare_operator():
    author = SpyAuthor()
    run_arm(Arm.EVOLVED, author=author)
    assert [op for op, _ in author.asked] == [Operator.COMPARE] * 5
    assert all(
        text.startswith("BEST GAME: ") and " WORST GAME: " in text for _, text in author.asked
    )


def test_the_selecting_arm_keeps_the_card_with_the_better_mean_in_every_generation():
    run = run_arm(Arm.EVOLVED)
    for row in run.rows:
        better = row["current"] if row["current_mean"] >= row["child_mean"] else row["child"]
        if row["current_mean"] != row["child_mean"]:
            assert row["kept"] == better


def test_the_controls_kept_card_ignores_the_means_and_the_selecting_arms_follows_them():
    def kept_pattern(arm, effect):
        run = run_arm(arm, player=FakePlayer(effect=effect))
        return [row["kept"] == row["child"] for row in run.rows]

    # Reversing what helps reverses the means; a coin does not notice, a comparison does.
    assert kept_pattern(Arm.NO_SELECTION, 0.06) == kept_pattern(Arm.NO_SELECTION, -0.06)
    forward, backward = kept_pattern(Arm.EVOLVED, 0.06), kept_pattern(Arm.EVOLVED, -0.06)
    assert forward != backward


def test_a_stored_child_is_reused_so_a_resume_never_asks_the_author_again():
    journal = MemoryJournal()
    first = SpyAuthor()
    run_arm(Arm.EVOLVED, author=first, journal=journal)
    second = SpyAuthor()
    again = run_arm(Arm.EVOLVED, author=second, journal=journal)
    assert second.asked == [] and len(first.asked) == 5 and len(again.rows) == 5


class RejectsEverything:
    def landmark(self, lesson):
        return Verdict(False, Rejection.LANDMARK, "second left to the blue-key room")


def test_three_rejected_children_stop_the_arm_with_the_prompt_error():
    with pytest.raises(MutationPromptError, match="no new child"):
        run_arm(Arm.EVOLVED, judge=RejectsEverything())


def test_the_noise_phase_replays_the_same_card_on_the_same_cases_once_per_player():
    cases = duel.noise_cases(SPLIT, 1)
    players = [FakePlayer(noise=0.3) for _ in range(5)]
    stats = dp.run_noise(START, cases, players)
    assert stats["games"] == 25 and stats["cases"] == 5.0 and stats["replicates"] == 5.0
    assert stats["replay_variance"] >= 0


def test_the_final_test_plays_three_cards_on_the_same_cases_and_pairs_them():
    selection, held_back = duel.final_cases(SPLIT, 1)
    cards = {"gen0": START, "control": seeds()[2], "evolved": seeds()[3]}
    scores = dp.run_final(cards, selection, held_back, {name: FakePlayer() for name in cards})
    assert all(len(per_case) == 24 for per_case in scores.values())
    table = dp.paired_table(scores, held_back, 1)
    assert len(table) == 9
    assert {row["label"].split(",")[0] for row in table} == {
        "evolved minus control", "evolved minus gen0", "control minus gen0",
    }  # fmt: skip
    all_rows = [row for row in table if row["label"].endswith(", all")]
    assert all(row["pairs"] == 24 for row in all_rows)
    assert {row["word"] for row in table} <= {"better", "worse", "tie"}
    held = [row for row in table if row["label"].endswith("held-back maps")]
    assert all(row["pairs"] == 12 for row in held)


def test_a_fitness_check_of_the_fake_world_the_door_cards_beat_the_empty_card():
    player = FakePlayer()
    case = duel.noise_cases(SPLIT, 1)[0]
    empty, door = Card.of([]), Card.of([Lesson("w", "Go through the door", "c")])
    assert fitness(player.play(door, case)) > fitness(player.play(empty, case))


def test_the_report_carries_the_noise_the_half_width_the_rows_and_the_paired_table():
    selection, held_back = duel.final_cases(SPLIT, 1)
    cards = {"gen0": START, "control": seeds()[2], "evolved": seeds()[3]}
    scores = dp.run_final(cards, selection, held_back, {name: FakePlayer() for name in cards})
    final = {
        "ids": {name: card.card_id for name, card in cards.items()},
        "means": {name: sum(v.values()) / len(v) for name, v in scores.items()},
        "games": {name: len(v) for name, v in scores.items()},
        "table": dp.paired_table(scores, held_back, 1),
    }
    arms = {
        "evolved": {"rows": run_arm(Arm.EVOLVED).rows},
        "control": {"rows": run_arm(Arm.NO_SELECTION).rows},
    }
    noise = dp.run_noise(
        START, duel.noise_cases(SPLIT, 1), [FakePlayer(noise=0.3) for _ in range(5)]
    )
    report = dp.build_report(noise, arms, final, {"calls": 0, "dollars": 0.0, "source": "ledger"})
    assert report["claim"] == "exploratory" and report["noise"]["paired_cases"] == 24
    assert report["noise"]["expected_half_width_of_a_paired_difference"] == pytest.approx(
        duel.expected_half_width(noise["replay_variance"], 24)
    )
    roles = {row["role"] for row in report["rows"]}
    assert roles == {"reference", "under_test"} and len(report["rows"]) == 3 + 10
    assert len(report["paired"]) == 9


def test_the_driver_refuses_to_start_a_game_when_it_only_reads_stored_ones():
    import run_duel

    with pytest.raises(RuntimeError, match="no stored game"):
        run_duel.NoPlayer().play(START, None)
    args = run_duel.parse_arguments(
        ["--phase", "evolve", "--arm", "control", "--root", "r", "--wad", "w", "--state", "s",
         "--best-card", "x"]
    )  # fmt: skip
    assert args.arm == "control" and args.phase == "evolve" and args.workers == 10
    assert sum(run_duel.CAPS.values()) < 3.0 and "random" in run_duel.CAPS


def test_a_random_operator_child_is_written_blind_to_the_traces_and_scored_against_its_parent():
    player = FakePlayer()
    parents = {}
    for generation in range(1, 6):
        parent = seeds()[generation]
        cases = duel.generation_cases(SPLIT, generation, 1)
        played = dp.play_pairs(player, [(parent, case) for case in cases])
        games = [played[(parent.card_id, case)] for case in cases]
        parents[generation] = (parent, games, sum(fitness(g) for g in games) / len(games))
    author = SpyAuthor()
    setup = dp.ArmSetup(
        Arm.NO_SELECTION, SPLIT, 1, player, author, AllowAllJudge(), MemoryJournal()
    )
    rows = dr.run_random_children(parents, setup)
    assert [row["generation"] for row in rows] == [1, 2, 3, 4, 5]
    assert {op for op, _ in author.asked} <= set(dr.RANDOM_OPERATORS)
    assert all("BEST GAME" not in text for _, text in author.asked)  # no best-versus-worst story
    assert all(row["games"] == 5 and row["arm"] == "random_operator" for row in rows)
    stats = duel.child_share(rows)
    assert (
        stats["children"] == 5.0 and 0.0 <= stats["low"] <= stats["share"] <= stats["high"] <= 1.0
    )


def test_the_random_operator_depends_on_the_seed_and_generation_only():
    assert dr.random_operator(1, 3) == dr.random_operator(1, 3)
    seen = {dr.random_operator(seed, g) for seed in range(10) for g in range(1, 6)}
    assert seen <= set(dr.RANDOM_OPERATORS) and len(seen) > 1


def test_the_report_scores_the_reflection_children_beside_the_random_operator_ones():
    selection, held_back = duel.final_cases(SPLIT, 1)
    cards = {"gen0": START, "control": seeds()[2], "evolved": seeds()[3]}
    scores = dp.run_final(cards, selection, held_back, {name: FakePlayer() for name in cards})
    final = {
        "ids": {name: card.card_id for name, card in cards.items()},
        "means": {name: sum(v.values()) / len(v) for name, v in scores.items()},
        "games": {name: len(v) for name, v in scores.items()},
        "table": dp.paired_table(scores, held_back, 1),
    }
    rows = [
        {"generation": g, "current": "a", "child": "b", "kept": "a",
         "current_mean": 0.1, "child_mean": 0.1 + 0.1 * (g % 2)}
        for g in range(1, 6)
    ]  # fmt: skip
    arms = {"evolved": {"rows": rows}, "control": {"rows": rows}, "random": {"rows": rows}}
    noise = {"replay_variance": 0.1}
    report = dp.build_report(noise, arms, final, {"calls": 0, "dollars": 0.0, "source": "ledger"})
    assert set(report["reflection"]) == {"evolved arm", "no-selection arm", "random operator"}
    assert report["reflection"]["evolved arm"]["beat_parent"] == 3.0
    assert len(report["rows"]) == 3 + 15


def test_two_names_holding_the_same_card_get_independent_games():
    class Counting(FakePlayer):
        pass

    selection, held_back = duel.final_cases(SPLIT, 1)
    cards = {"gen0": START, "control": START, "evolved": seeds()[3]}
    players = {name: Counting() for name in cards}
    scores = dp.run_final(cards, selection, held_back, players)
    assert [p.calls for p in players.values()] == [24, 24, 24]  # 72 games, none shared
    assert scores["gen0"] == scores["control"]  # the fake is deterministic; a model would differ


def run3_arm(arm, effect=0.06, journal=None, author=None):
    player = FakePlayer(effect=effect)
    setup = dp.ArmSetup(
        arm, SPLIT, 1, player, author or SpyAuthor(), AllowAllJudge(), journal or MemoryJournal(),
        duel.RUN3,
    )  # fmt: skip
    games = [player.play(START, case) for case in duel.noise_cases(SPLIT, 1)]
    return dp.ArmRunner(setup).go(START, games), player


def test_run_three_arms_play_one_hundred_sixty_games_with_three_children_a_generation():
    for arm in (Arm.EVOLVED, Arm.NO_SELECTION):
        run, player = run3_arm(arm)
        assert [row["games"] for row in run.rows] == [40, 40, 40, 40]
        assert all(len(row["children"]) == 3 for row in run.rows)
        assert len(dp.reflection_rows(run.rows)) == 12
        assert player.calls - 5 == 160  # five start games came from run 2's replay


def test_run_three_selecting_arm_keeps_the_best_of_four_and_the_control_ignores_the_means():
    def kept(arm, effect):
        run, _ = run3_arm(arm, effect)
        return [row["kept"] == row["current"] for row in run.rows]

    assert kept(Arm.NO_SELECTION, 0.06) == kept(Arm.NO_SELECTION, -0.06)
    run, _ = run3_arm(Arm.EVOLVED)
    for row in run.rows:
        means = {row["current"]: row["current_mean"]} | {
            c["id"]: c["mean"] for c in row["children"]
        }
        assert means[row["kept"]] == max(means.values())


def test_run_three_stores_all_three_children_before_their_games_and_reuses_them():
    journal = MemoryJournal()
    first = SpyAuthor()
    run3_arm(Arm.EVOLVED, journal=journal, author=first)
    assert len(first.asked) >= 12 and all(len(c[0]) == 3 for c in journal.stored.values())
    second = SpyAuthor()
    run3_arm(Arm.EVOLVED, journal=journal, author=second)
    assert second.asked == []


def test_run_three_random_operator_children_are_three_a_generation_and_blind_to_the_traces():
    player = FakePlayer()
    parents = {}
    for generation in range(1, 5):
        parent = seeds()[generation]
        cases = duel.generation_cases(SPLIT, generation, 1, duel.RUN3)
        played = dp.play_pairs(player, [(parent, case) for case in cases])
        games = [played[(parent.card_id, case)] for case in cases]
        parents[generation] = (parent, games, sum(fitness(g) for g in games) / len(games))
    author = SpyAuthor()
    setup = dp.ArmSetup(
        Arm.NO_SELECTION, SPLIT, 1, player, author, AllowAllJudge(), MemoryJournal(), duel.RUN3
    )
    rows = dr.run_random_children(parents, setup)
    assert len(rows) == 12 and all(row["games"] == 10 for row in rows)
    assert all("BEST GAME" not in text for _, text in author.asked)
    assert {row["operator"] for row in rows} <= {op.value for op in dr.RANDOM_OPERATORS}
    assert duel.child_share(rows)["children"] == 12.0
