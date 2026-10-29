"""The engine player against a fake game: grading, ungraded errors, hold-out, cuts."""

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from nav_world import START, two_rooms, two_rooms_index

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import play_case  # noqa: E402 - needs the scripts path added above

from symbiont.act1.card_genome import Card, Lesson  # noqa: E402
from symbiont.act1.episode import MapKnowledge  # noqa: E402
from symbiont.act1.game_fitness import Case, Grade  # noqa: E402
from symbiont.act1.glimmer import GlimmerReplyError, Reply  # noqa: E402
from symbiont.act1.levels import HeldOutLevelError  # noqa: E402
from symbiont.act1.map_index import MapIndex  # noqa: E402
from symbiont.act1.move_cuts import CutSetting, MoveCuts  # noqa: E402
from symbiont.act1.navmap import build_navmap  # noqa: E402
from symbiont.act1.rooms import RoomFinder  # noqa: E402
from symbiont.act1.wad import Sector  # noqa: E402
from symbiont.eval.prereg import PreregNotFrozenError  # noqa: E402

pytestmark = pytest.mark.periphery
CASE = Case("MAP01", 7, 3, CutSetting.NONE)
CARD = Card.of([Lesson("Wandered", "Walk to the next door", "Is a door in view?")])


class FakeGame:
    """A game that never moves; `finish_after` actions it reports the episode as finished."""

    def __init__(self, finish_after=None, dead=False, kills=0):
        self.actions, self.finish_after, self.dead, self.kills = 0, finish_after, dead, kills
        self.closed = False

    def new_episode(self):
        pass

    def close(self):
        self.closed = True

    def is_episode_finished(self):
        return self.dead or (self.finish_after is not None and self.actions >= self.finish_after)

    def is_player_dead(self):
        return self.dead

    def get_episode_time(self):
        return 100

    def get_episode_timeout(self):
        return 20000

    def get_state(self):
        return SimpleNamespace(
            game_variables=[100, 50, START[0], START[1], 0.0],
            labels=[],
            objects=[],
            sectors=[SimpleNamespace(floor_height=16, ceiling_height=128)],
            depth_buffer=np.full((240, 320), 60, dtype=np.uint8),
        )

    def make_action(self, vector):
        self.actions += 1


def loader_for(game, calls):
    geometry, _ = two_rooms_index(two_rooms())
    nav = build_navmap(geometry, two_rooms_index(geometry)[1])
    knowledge = MapKnowledge(MapIndex((), (), (), (Sector(16, 128),)), nav)

    def load(wad, case):
        calls.append(case.level)
        return game, knowledge, RoomFinder(geometry)

    return load


def player(tmp_path, game, reply, calls=None, **setup_extra):
    setup = play_case.EngineSetup(
        wad=tmp_path / "x.wad",
        episodes=tmp_path / "episodes",
        decisions=3,
        loader=loader_for(game, [] if calls is None else calls),
        kills=lambda g: g.kills,
        **setup_extra,
    )
    return play_case.EnginePlayer(lambda card, case: reply, setup)


def turn(prompt):
    return Reply("turn(90)", "stop", 0)


def test_an_exit_is_graded_with_the_whole_route_covered(tmp_path):
    game = FakeGame(finish_after=1, kills=2)
    result = player(tmp_path, game, turn).play(CARD, CASE)
    assert result.grade is Grade.GRADED and result.exit_reached and not result.died
    assert result.route_share == 1.0 and result.kills == 2 and result.card_id == CARD.card_id
    assert game.closed


def test_a_game_that_goes_nowhere_has_a_route_share_between_zero_and_one_and_tagged_pains(tmp_path):
    result = player(tmp_path, FakeGame(), turn).play(CARD, CASE)
    assert not result.exit_reached and 0.0 <= result.route_share <= 1.0
    assert result.mistakes == sum(count for _, count in result.pains) > 0
    assert dict(result.pains)["wasted_move"] >= 1


def test_a_death_is_recorded_as_died(tmp_path):
    result = player(tmp_path, FakeGame(dead=True), turn).play(CARD, CASE)
    assert result.died and not result.exit_reached


def test_a_glimmer_error_makes_the_game_ungraded_with_the_error_class_as_its_reason(tmp_path):
    def broken(prompt):
        raise GlimmerReplyError("no usage")

    result = player(tmp_path, FakeGame(), broken).play(CARD, CASE)
    assert result.grade is Grade.UNGRADED and result.ungraded_reason == "GlimmerReplyError"
    assert not result.exit_reached and result.route_share == 0.0


class SpendCapError(RuntimeError):
    """Stands in for the ledger's cap error, which the engine player must never catch."""


def test_an_error_outside_the_ungradable_list_propagates_and_stops_the_run(tmp_path):
    def over_the_cap(prompt):
        raise SpendCapError("cap reached")

    game = FakeGame()
    with pytest.raises(SpendCapError):
        player(tmp_path, game, over_the_cap).play(CARD, CASE)
    assert game.closed


def test_a_held_out_level_raises_before_any_engine_call(tmp_path):
    calls = []
    with pytest.raises(HeldOutLevelError):
        player(tmp_path, FakeGame(), turn, calls).play(CARD, Case("MAP04", 1, 3, CutSetting.NONE))
    assert calls == []


def test_the_cut_setting_reaches_the_run_log_and_cut_moves_are_counted(tmp_path, monkeypatch):
    seen = []

    def every_move_cut(setting, seed):
        seen.append((setting, seed))
        return MoveCuts(share=1.0, seed=seed)

    monkeypatch.setattr(play_case, "cuts_for", every_move_cut)
    case = Case("MAP01", 7, 2, CutSetting.TEN_PERCENT)
    result = player(tmp_path, FakeGame(), turn).play(CARD, case)
    assert seen == [(CutSetting.TEN_PERCENT, 7)]
    assert result.cut_moves == 3


def test_the_card_text_reaches_the_model_before_the_game_prompt(tmp_path):
    prompts = []

    def record(prompt):
        prompts.append(prompt)
        return Reply("turn(90)", "stop", 0)

    player(tmp_path, FakeGame(), record).play(CARD, CASE)
    assert prompts and prompts[0].startswith("Lessons from earlier games:")
    assert "Walk to the next door" in prompts[0]


def test_the_decision_log_goes_under_the_episodes_directory(tmp_path):
    player(tmp_path, FakeGame(), turn).play(CARD, CASE)
    assert (tmp_path / "episodes" / f"{CARD.card_id}-MAP01-s7.jsonl").is_file()


HELD_OUT_CASE = Case("MAP04", 1001, 3, CutSetting.NONE)
FROZEN = SimpleNamespace(path="prereg/x.md", commit="abc", sha256="def")


def final_test_player(tmp_path, calls, **setup_extra):
    return player(tmp_path, FakeGame(), turn, calls, **setup_extra)


def test_a_frozen_prereg_alone_does_not_open_a_held_out_level(tmp_path):
    calls = []
    with pytest.raises(HeldOutLevelError):
        final_test_player(tmp_path, calls, frozen_prereg=FROZEN).play(CARD, HELD_OUT_CASE)
    assert calls == []


def test_the_final_test_mode_needs_a_frozen_prereg(tmp_path):
    calls = []
    with pytest.raises(PreregNotFrozenError):
        final_test_player(
            tmp_path, calls, mode=play_case.RunMode.FINAL_TEST, final_levels=frozenset({"MAP04"})
        ).play(CARD, HELD_OUT_CASE)
    assert calls == []


def test_the_final_test_plays_only_the_levels_the_prereg_names(tmp_path):
    calls = []
    setup = {
        "mode": play_case.RunMode.FINAL_TEST,
        "frozen_prereg": FROZEN,
        "final_levels": frozenset({"MAP04"}),
    }
    with pytest.raises(play_case.NotInFinalTestError):
        final_test_player(tmp_path, calls, **setup).play(
            CARD, Case("MAP08", 1001, 3, CutSetting.NONE)
        )
    assert calls == []
    result = final_test_player(tmp_path, calls, **setup).play(CARD, HELD_OUT_CASE)
    assert result.grade is Grade.GRADED and calls == ["MAP04"]


def test_a_level_with_no_map_data_raises_and_closes_the_game_never_a_graded_zero(tmp_path):
    game = FakeGame()
    no_nav = MapKnowledge(MapIndex((), (), (), (Sector(16, 128),)), None)
    setup = play_case.EngineSetup(
        wad=tmp_path / "x.wad",
        episodes=tmp_path / "episodes",
        loader=lambda wad, case: (game, no_nav, RoomFinder(two_rooms())),
    )
    with pytest.raises(play_case.MissingMapError, match="MAP01"):
        play_case.EnginePlayer(lambda card, case: turn, setup).play(CARD, CASE)
    assert game.closed


def threads(workers):
    import concurrent.futures

    return concurrent.futures.ThreadPoolExecutor(workers)


def many_player(tmp_path, reply, workers):
    setup = play_case.EngineSetup(
        wad=tmp_path / "x.wad",
        episodes=tmp_path / "episodes",
        decisions=2,
        loader=loader_for(FakeGame(), []),
        kills=lambda g: 0,
        workers=workers,
        executor_factory=threads,
    )
    return play_case.EnginePlayer(lambda card, case: reply, setup)


def test_play_many_reports_every_game_as_it_finishes_and_the_worker_count_does_not_change_them(
    tmp_path,
):
    cases = [Case("MAP01", seed, 3, CutSetting.NONE) for seed in range(4)]
    pairs = [(CARD, case) for case in cases]
    heard = {}
    for workers in (1, 3):
        got = []
        sink = got.append
        many_player(tmp_path, turn, workers).play_many(
            pairs, lambda c, k, r, sink=sink: sink((k, r))
        )
        heard[workers] = {case: result for case, result in got}
        assert len(got) == 4
    assert heard[1].keys() == heard[3].keys()
    assert {c: r.route_share for c, r in heard[1].items()} == {
        c: r.route_share for c, r in heard[3].items()
    }


def test_play_many_stops_on_a_spend_cap_and_lets_it_propagate(tmp_path):
    def over_the_cap(prompt):
        raise SpendCapError("cap reached")

    cases = [Case("MAP01", seed, 3, CutSetting.NONE) for seed in range(4)]
    with pytest.raises(SpendCapError):
        many_player(tmp_path, over_the_cap, 2).play_many(
            [(CARD, case) for case in cases], lambda *_: None
        )


def test_the_engine_player_with_spark_players_can_be_pickled_for_a_process_pool(tmp_path):
    import pickle

    import spark_players

    from symbiont.egress.spark import Effort

    setup = play_case.EngineSetup(wad=tmp_path / "x.wad", episodes=tmp_path / "e", workers=2)
    maker = spark_players.SparkPlayers("run-x", 3.0, Effort.LOW)
    revived = pickle.loads(pickle.dumps(play_case.EnginePlayer(maker, setup)))
    assert revived.reply_for == maker and revived.setup.workers == 2


def fake_run(before, after=None):
    spot = lambda xy: SimpleNamespace(position=xy)  # noqa: E731 - tiny stand-in for a game view
    return SimpleNamespace(before=spot(before), after=None if after is None else spot(after))


def test_progress_is_the_furthest_routable_spot_and_an_unroutable_spot_is_skipped(monkeypatch):
    from symbiont.act1.game_fitness import NoRouteError

    remaining = {(0.0, 0.0): 100.0, (10.0, 0.0): 60.0, (20.0, 0.0): 90.0}

    def fake_remaining(_nav, spot):
        if spot not in remaining:
            raise NoRouteError("off the grid")
        return remaining[spot]

    monkeypatch.setattr(play_case, "remaining_route_units", fake_remaining)
    runs = [fake_run((0.0, 0.0), (10.0, 0.0)), fake_run((10.0, 0.0), (20.0, 0.0)),
            fake_run((20.0, 0.0), (999.0, 999.0))]  # fmt: skip
    share = play_case.EnginePlayer._share(None, runs, 100.0, play_case.EpisodeEnd.DECISION_CAP)
    assert share == pytest.approx(0.4)  # furthest was 60 units left of 100, not the last spot
    assert play_case.EnginePlayer._share(None, [], 100.0, play_case.EpisodeEnd.DECISION_CAP) == 0.0
