"""The collector script: refusals come before any game starts, and failures name their episode."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from room_world import two_rooms_with_a_pillar
from symbiont.act1.env_text import GameStateView, Layout
from symbiont.act1.levels import HeldOutLevelError
from symbiont.act1.rooms import RoomFinder
from symbiont.act1.steplog import MoveKind, MoveRun
from symbiont.records.schema import load_jsonl

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "act1" / "collect_episodes.py"
IN_ROOM_0 = (10.0, 10.0)


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so the stubs of one test never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


class StubGame:
    def __init__(self):
        self.seeds = []
        self.closed = False

    def set_seed(self, seed):
        self.seeds.append(seed)

    def is_player_dead(self):
        return False

    def is_episode_finished(self):
        return False

    def close(self):
        self.closed = True


def view(position):
    return GameStateView(
        health=80.0,
        ammo=20.0,
        position=position,
        angle_deg=90.0,
        objects=(),
        doors=(),
        keys_held=(),
        layout=Layout(True, True, True, False),
        exits=(),
        closed_sectors=frozenset(),
    )


def one_move():
    return MoveRun(
        0, "walk to exit", MoveKind.WALK, "arrived", 12, view(IN_ROOM_0), view(IN_ROOM_0)
    )


def load_script(monkeypatch, tmp_path, *, moves=1, loader=None, play=None):
    spec = importlib.util.spec_from_file_location("collect_episodes_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    game = StubGame()
    rooms = RoomFinder(two_rooms_with_a_pillar())

    def stub_load_level(wad, level):
        return game, "knowledge", rooms

    def stub_run_episode(_game, _reply, _decisions, run_log, *, knowledge):
        for _ in range(moves):
            run_log.on_move(one_move())
        return []

    monkeypatch.setattr(module, "wad_path", lambda out: tmp_path / "wad")
    monkeypatch.setattr(module, "load_level", loader or stub_load_level)
    monkeypatch.setattr(module, "run_episode", play or stub_run_episode)
    return module, game


def collect(module, tmp_path, *extra):
    argv = ["--levels", "MAP01", "--policies", "random", "--seeds", "1-1"]
    module.main([*argv, "--out", str(tmp_path / "out"), *extra])


def test_collector_writes_one_file_and_one_summary_line_per_episode(monkeypatch, tmp_path, capsys):
    module, game = load_script(monkeypatch, tmp_path, moves=2)
    collect(module, tmp_path, "--seeds", "1-2")
    summaries = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(s["level"], s["policy"], s["seed"], s["records"]) for s in summaries] == [
        ("MAP01", "random", 1, 2),
        ("MAP01", "random", 2, 2),
    ]
    assert {"rejected", "pains", "seconds", "ended"} <= set(summaries[0])
    assert summaries[0]["ended"] == "decision cap"
    assert game.seeds == [1, 2]
    assert game.closed
    path = tmp_path / "out" / "MAP01" / "MAP01-random-s1.jsonl"
    assert len(list(load_jsonl(path.open()))) == 2


def test_collector_refuses_a_held_out_level_before_starting_any_game(monkeypatch, tmp_path):
    def never(wad, level):
        raise AssertionError("a game was started")

    module, _ = load_script(monkeypatch, tmp_path, loader=never)
    with pytest.raises(HeldOutLevelError):
        module.main(["--levels", "MAP01,MAP04", "--out", str(tmp_path / "out")])


def test_collector_refuses_to_overwrite_an_existing_episode_file(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path)
    existing = tmp_path / "out" / "MAP01" / "MAP01-random-s1.jsonl"
    existing.parent.mkdir(parents=True)
    existing.write_text("kept\n")
    with pytest.raises(FileExistsError, match="MAP01-random-s1.jsonl"):
        collect(module, tmp_path)
    assert existing.read_text() == "kept\n"


def test_collector_names_the_episode_when_playing_fails(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    module, _ = load_script(monkeypatch, tmp_path, play=boom)
    with pytest.raises(RuntimeError, match="boom") as caught:
        collect(module, tmp_path)
    assert any("MAP01-random-s1" in note for note in caught.value.__notes__)


def test_collector_refuses_an_episode_with_no_moves(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path, moves=0)
    with pytest.raises(RuntimeError, match="no moves played: MAP01-random-s1"):
        collect(module, tmp_path)


def test_collector_names_the_level_when_loading_fails(monkeypatch, tmp_path):
    def broken(wad, level):
        raise OSError("no wad")

    module, _ = load_script(monkeypatch, tmp_path, loader=broken)
    with pytest.raises(OSError, match="no wad") as caught:
        collect(module, tmp_path)
    assert any("MAP01" in note for note in caught.value.__notes__)
