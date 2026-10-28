"""The collector script: refusals come before any game starts, and failures name their episode."""

import importlib.util
import json
import subprocess
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


class StubGame:
    def __init__(self, dead=False, finished=False, time=0, timeout=100):
        self.seeds = []
        self.closed = False
        self.dead = dead
        self.finished = finished
        self.time = time
        self.timeout = timeout

    def set_seed(self, seed):
        self.seeds.append(seed)

    def is_player_dead(self):
        return self.dead

    def is_episode_finished(self):
        return self.finished

    def get_episode_time(self):
        return self.time

    def get_episode_timeout(self):
        return self.timeout

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

    monkeypatch.setattr(module, "wad_path", lambda: tmp_path / "wad")
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
    assert summaries[0]["ended"] == "decision_cap"
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


@pytest.mark.parametrize(
    ("game", "expected"),
    [
        (StubGame(dead=True, finished=True), "died"),
        (StubGame(finished=True, time=10), "exited"),
        (StubGame(finished=True, time=100, timeout=100), "timed_out"),
        (StubGame(), "decision_cap"),
    ],
)
def test_how_it_ended_tells_death_exit_timeout_and_cap_apart(monkeypatch, tmp_path, game, expected):
    module, _ = load_script(monkeypatch, tmp_path)
    assert module.how_it_ended(game).value == expected


def test_the_last_record_on_disk_carries_how_the_episode_ended(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path, moves=2)
    collect(module, tmp_path)
    path = tmp_path / "out" / "MAP01" / "MAP01-random-s1.jsonl"
    ended = [json.loads(r.raw)["ended"] for r in load_jsonl(path.open())]
    assert ended == [None, "decision_cap"]


def test_the_game_is_closed_when_an_episode_raises(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    module, game = load_script(monkeypatch, tmp_path, play=boom)
    with pytest.raises(RuntimeError, match="boom"):
        collect(module, tmp_path)
    assert game.closed


def test_a_failure_mid_write_leaves_no_file_at_the_final_path(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path)

    def broken_dump(_records, _handle):
        raise OSError("disk full")

    monkeypatch.setattr(module, "dump_jsonl", broken_dump)
    with pytest.raises(OSError, match="disk full"):
        collect(module, tmp_path)
    assert not (tmp_path / "out" / "MAP01" / "MAP01-random-s1.jsonl").exists()


def test_two_arms_alternate_on_each_seed_so_server_drift_hits_both(monkeypatch, tmp_path, capsys):
    module, _ = load_script(monkeypatch, tmp_path)
    collect(module, tmp_path, "--policies", "random,scripted_explorer", "--seeds", "1-2")
    order = [
        (s["seed"], s["policy"]) for s in map(json.loads, capsys.readouterr().out.splitlines())
    ]
    assert order == [
        (1, "random"),
        (1, "scripted_explorer"),
        (2, "random"),
        (2, "scripted_explorer"),
    ]


def test_the_summary_reports_decisions_tokens_and_split(monkeypatch, tmp_path, capsys):
    module, _ = load_script(monkeypatch, tmp_path)
    collect(module, tmp_path)
    summary = json.loads(capsys.readouterr().out)
    assert summary["split"] == "training" and summary["decisions"] == 0
    assert summary["tokens_in"] is None and summary["tokens_out"] is None  # no model was called


def test_the_decision_log_goes_beside_the_records(monkeypatch, tmp_path):
    seen = {}

    def play(_game, _reply, _decisions, run_log, *, knowledge):
        seen["path"] = run_log.path
        run_log.on_move(one_move())
        return []

    module, _ = load_script(monkeypatch, tmp_path, play=play)
    collect(module, tmp_path)
    assert seen["path"] == tmp_path / "out" / "MAP01" / "MAP01-random-s1.decisions.jsonl"


def glimmer_args(module, *extra):
    return module.parse_arguments(["--policies", "glimmer_plain,glimmer_personal", *extra])


def test_glimmer_arms_need_the_server_url_from_the_environment(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path)
    monkeypatch.delenv("SYMBIONT_GLIMMER_URL", raising=False)
    with pytest.raises(RuntimeError, match="SYMBIONT_GLIMMER_URL"):
        module.policy_maker(glimmer_args(module, "--adapters", "1"))


def test_the_personal_arm_is_refused_without_an_adapter_server(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path)
    monkeypatch.setenv("SYMBIONT_GLIMMER_URL", "http://127.0.0.1:8093/v1")
    with pytest.raises(ValueError, match="glimmer_personal needs --adapters"):
        module.policy_maker(glimmer_args(module))


def test_glimmer_arms_become_policies_named_after_the_arm(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path)
    monkeypatch.setenv("SYMBIONT_GLIMMER_URL", "http://127.0.0.1:8093/v1")
    make = module.policy_maker(glimmer_args(module, "--adapters", "1"))
    assert make("glimmer_personal", 3).name == "glimmer_personal"
    assert make("random", 3).name == "random"


def test_a_held_out_level_needs_a_frozen_prereg(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path)
    draft = tmp_path / "draft.md"
    draft.write_text("# Prereg\n\n**DRAFT.** The freeze writes **FROZEN <date>.** here.\n")
    with pytest.raises(module.PreregNotFrozenError, match="not frozen"):
        module.main(["--levels", "MAP04", "--scored", str(draft), "--out", str(tmp_path / "o")])
    frozen_but_untracked = tmp_path / "frozen.md"
    frozen_but_untracked.write_text("# Prereg\n\n**FROZEN 2026-10-29.**\n")
    with pytest.raises(module.PreregNotFrozenError, match="not committed"):
        module.require_frozen_prereg(frozen_but_untracked)


@pytest.mark.periphery  # runs git in a scratch repository
def test_a_committed_frozen_prereg_returns_its_hash_and_an_edit_is_refused(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    prereg = repo / "p.md"
    prereg.write_text("**FROZEN 2026-10-29.**\n")

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("add", "p.md")
    git("-c", "user.name=t", "-c", "user.email=test", "commit", "-qm", "freeze")
    assert len(module.require_frozen_prereg(prereg)) == 64
    prereg.write_text("**FROZEN 2026-10-29.**\nedited\n")
    with pytest.raises(module.PreregNotFrozenError, match="differs from HEAD"):
        module.require_frozen_prereg(prereg)
