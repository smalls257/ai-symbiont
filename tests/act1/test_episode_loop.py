"""Reply classification, key tracking and the incremental log, against a stub engine."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from symbiont.act1.engine import (
    KeyTracker,
    KeyTrackingError,
    SectorConventionError,
    check_sector_convention,
    view_from_engine,
)
from symbiont.act1.episode import MapKnowledge, RunLog, run_episode
from symbiont.act1.glimmer import Reply, parse_chat_response
from symbiont.act1.map_index import MapIndex, build_index
from symbiont.act1.steplog import MoveKind
from symbiont.act1.wad import Sector, read_map
from wad_builder import sample_wad


def chat_json(content, finish_reason, reasoning=None):
    message = {"content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


def test_parse_chat_response_keeps_finish_reason_and_reasoning_size():
    reply = parse_chat_response(chat_json("", "length", reasoning="thinking " * 10))
    assert reply == Reply(text="", finish_reason="length", reasoning_chars=90)
    assert parse_chat_response(chat_json(" turn(90) ", "stop")) == Reply("turn(90)", "stop", 0)


NO_MAP = MapIndex((), (), ())


def engine_state(objects=(), position=(0.0, 0.0)):
    return SimpleNamespace(
        game_variables=[100, 50, position[0], position[1], 0.0],
        labels=[],
        objects=[
            SimpleNamespace(id=i, name=n, position_x=x, position_y=y) for i, n, x, y in objects
        ],
        sectors=[],
        depth_buffer=np.full((240, 320), 60, dtype=np.uint8),
    )


def test_key_tracker_reports_a_key_that_vanishes_next_to_the_player():
    tracker = KeyTracker()
    assert tracker.update(engine_state([(7, "BlueCard", 100.0, 0.0)], (60.0, 0.0))) == ()
    assert tracker.update(engine_state([], (96.0, 0.0))) == ("BlueCard",)
    assert tracker.update(engine_state([], (200.0, 0.0))) == ("BlueCard",)  # still held


def test_key_tracker_raises_when_a_key_vanishes_far_away():
    tracker = KeyTracker()
    tracker.update(engine_state([(7, "RedSkull", 900.0, 0.0)]))
    with pytest.raises(KeyTrackingError, match="RedSkull"):
        tracker.update(engine_state([]))


def test_view_from_engine_carries_held_keys():
    tracker = KeyTracker()
    view_from_engine(engine_state([(7, "BlueCard", 10.0, 0.0)]), tracker, NO_MAP)
    assert view_from_engine(engine_state([]), tracker, NO_MAP).keys_held == ("BlueCard",)


class FakeGame:
    def __init__(self):
        self.actions = []

    def new_episode(self):
        pass

    def is_episode_finished(self):
        return False

    def get_state(self):
        return engine_state()

    def make_action(self, vector):
        self.actions.append(vector)


def scripted_replies(*replies):
    queue = iter(replies)

    def reply_fn(prompt):
        item = next(queue)
        if isinstance(item, Exception):
            raise item
        return item

    return reply_fn


def test_truncated_reply_is_classified_truncated_not_invalid_and_runs_no_move():
    game = FakeGame()
    decisions = run_episode(
        game, scripted_replies(Reply("turn(9", "length", 800)), 1, knowledge=MapKnowledge(NO_MAP)
    )
    assert decisions[0].status == "truncated"
    assert decisions[0].finish_reason == "length"
    assert decisions[0].reasoning_chars == 800
    assert game.actions == []


def test_invalid_reply_is_rejected_never_defaulted_to_a_move():
    game = FakeGame()
    decisions = run_episode(
        game, scripted_replies(Reply("explore()", "stop", 0)), 1, knowledge=MapKnowledge(NO_MAP)
    )
    assert decisions[0].status == "invalid"
    assert "explore" in decisions[0].rejected
    assert game.actions == []


def test_log_is_written_one_line_per_decision_and_survives_a_crash(tmp_path):
    log = tmp_path / "runs" / "episode.jsonl"
    replies = scripted_replies(Reply("explore()", "stop", 0), ConnectionError("model down"))
    with pytest.raises(ConnectionError):
        run_episode(FakeGame(), replies, 5, RunLog(log), knowledge=MapKnowledge(NO_MAP))
    lines = log.read_text().splitlines()
    assert len(lines) == 2  # run header, then the one finished decision
    assert "run_header" in json.loads(lines[0])
    assert json.loads(lines[1])["status"] == "invalid"


def test_rerun_appends_a_new_header_and_keeps_earlier_evidence(tmp_path):
    log = tmp_path / "episode.jsonl"
    run_episode(
        FakeGame(),
        scripted_replies(Reply("explore()", "stop", 0)),
        1,
        RunLog(log, {"model": "m1"}),
        knowledge=MapKnowledge(NO_MAP),
    )
    run_episode(
        FakeGame(),
        scripted_replies(Reply("explore()", "stop", 0)),
        1,
        RunLog(log, {"model": "m2"}),
        knowledge=MapKnowledge(NO_MAP),
    )
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    headers = [r["run_header"] for r in rows if "run_header" in r]
    assert [h["model"] for h in headers] == ["m1", "m2"]
    assert all("started_at" in h and h["max_decisions"] == 1 for h in headers)
    assert len(rows) == 4


def engine_sector(floor, ceiling):
    # ViZDoom 1.2 reports floor_height as the negated WAD floor; ceiling_height is as authored.
    return SimpleNamespace(floor_height=-floor, ceiling_height=ceiling)


def test_view_from_engine_uses_the_wad_index_for_doors_exits_and_reach():
    index = build_index(read_map(sample_wad(), "MAP01"))
    state = engine_state(position=(110.0, 32.0))
    state.sectors = [engine_sector(0, 128), engine_sector(0, 0), engine_sector(0, 128)]
    view = view_from_engine(state, KeyTracker(), index)
    assert [d.key_colour for d in view.reach_doors] == ["blue"]
    assert view.doors == ()  # facing +x from x=110, the door at x=100 is behind


def test_view_from_engine_stops_listing_a_door_once_its_sector_opens():
    index = build_index(read_map(sample_wad(), "MAP01"))
    state = engine_state(position=(110.0, 32.0))
    state.sectors = [engine_sector(0, 128), engine_sector(0, 128), engine_sector(0, 128)]
    assert view_from_engine(state, KeyTracker(), index).reach_doors == ()


def test_sector_convention_check_passes_when_engine_matches_the_wad():
    wad_sectors = [Sector(-64, -64), Sector(16, 16)]
    check_sector_convention(wad_sectors, [engine_sector(-64, -64), engine_sector(16, 16)])


def test_sector_convention_check_raises_when_engine_heights_disagree_with_the_wad():
    wad_sectors = [Sector(-64, -64)]
    with pytest.raises(SectorConventionError, match="sector 0"):
        check_sector_convention(
            wad_sectors, [SimpleNamespace(floor_height=-64, ceiling_height=-64)]
        )
    with pytest.raises(SectorConventionError, match="count"):
        check_sector_convention(wad_sectors, [])


def test_prompt_offers_open_door():
    from symbiont.act1.episode import build_prompt

    assert "open_door" in build_prompt("x", [])


def test_prompt_offers_go_to():
    from symbiont.act1.episode import build_prompt

    assert "go_to(" in build_prompt("x", [])


def test_view_from_engine_carries_every_closed_sector_seen_or_not():
    index = build_index(read_map(sample_wad(), "MAP01"))
    state = engine_state(position=(110.0, 32.0))
    state.sectors = [engine_sector(0, 128), engine_sector(0, 0), engine_sector(0, 128)]
    assert view_from_engine(state, KeyTracker(), index).closed_sectors == frozenset({1})


def test_run_episode_with_a_map_adds_routes_to_the_observation_and_parses_go_to_with_it():
    from nav_world import START, two_rooms, two_rooms_index
    from symbiont.act1.navmap import build_navmap

    geometry, index = two_rooms_index(two_rooms())
    game = FakeGame()
    game.get_state = lambda: engine_state(position=START)
    decisions = run_episode(
        game,
        scripted_replies(Reply("go_to(Banana)", "stop", 0)),
        1,
        knowledge=MapKnowledge(NO_MAP, build_navmap(geometry, index)),
    )
    assert "Reachable with go_to: " in decisions[0].observation
    assert "exit: " in decisions[0].observation and "units by path" in decisions[0].observation
    assert decisions[0].outcomes == (
        "scripted go_to(Banana) -> Banana not visible, "
        "and it is not a door, exit or key on the map",
    )


TWO_TURNS_THEN_SHOOT = (
    Reply("turn(90)\nturn(-90)", "stop", 0),
    Reply("shoot_nearest()", "stop", 0),
)


def test_run_episode_reports_each_played_move_with_its_tics():
    game, runs = FakeGame(), []
    run_episode(
        game,
        scripted_replies(*TWO_TURNS_THEN_SHOOT),
        2,
        RunLog(on_move=runs.append),
        knowledge=MapKnowledge(NO_MAP),
    )
    assert [r.decision for r in runs] == [0, 0, 1]
    assert runs[0].kind == MoveKind.TURN and runs[0].label == "scripted turn(90)"
    assert runs[0].outcome == "timeout after 60 tics"
    assert runs[2].outcome == "no enemy visible" and runs[2].tics == 0
    assert sum(r.tics for r in runs) == len(game.actions) == 120


def test_run_episode_without_an_observer_behaves_as_before():
    game = FakeGame()
    decisions = run_episode(
        game, scripted_replies(*TWO_TURNS_THEN_SHOOT), 2, knowledge=MapKnowledge(NO_MAP)
    )
    assert decisions[0].outcomes == (
        "scripted turn(90) -> timeout after 60 tics",
        "scripted turn(-90) -> timeout after 60 tics",
    )
    assert decisions[1].outcomes == ("scripted shoot_nearest() -> no enemy visible",)
    assert len(game.actions) == 120
