"""Level smoke test: failing levels are dropped with a reason; the published file is labels."""

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nav_world import START, trench_rooms, two_rooms
from wad_builder import sample_wad

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import smoke_levels  # noqa: E402 - needs the scripts path added above

from symbiont.act1.evolve_split import EvolveSplit, SmokeResult  # noqa: E402
from symbiont.act1.wad import Thing  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.periphery


def with_start(geometry, at=START):
    return dataclasses.replace(geometry, things=[Thing(int(at[0]), int(at[1]), 1)])


def test_a_level_with_a_route_from_the_start_to_an_exit_passes():
    assert smoke_levels.static_route_check(with_start(two_rooms())).passed


def test_a_level_with_no_route_is_dropped_with_the_nav_reason():
    result = smoke_levels.static_route_check(with_start(trench_rooms(width=64)))
    assert not result.passed and result.reason.startswith("no_route:") and "exit" in result.reason


def test_a_level_without_a_player_start_is_dropped():
    bare = dataclasses.replace(two_rooms(), things=[])
    assert smoke_levels.static_route_check(bare).reason.startswith("no_start")


class FakeGame:
    def __init__(self, crash=False):
        self.crash, self.closed = crash, False

    def close(self):
        self.closed = True


def test_a_level_whose_engine_load_crashes_is_dropped_with_the_exception_class(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(smoke_levels, "static_route_check", lambda geometry: smoke_levels.PASS)
    wad = tmp_path / "x.wad"
    wad.write_bytes(sample_wad())

    def crashing(_wad, _level):
        raise RuntimeError("engine died")

    assert smoke_levels.smoke_level(wad, "MAP01", crashing) == SmokeResult(
        passed=False, reason="crash: RuntimeError"
    )


def test_a_level_missing_from_the_wad_is_dropped_as_a_crash_not_skipped(tmp_path):
    wad = tmp_path / "x.wad"
    wad.write_bytes(sample_wad())
    result = smoke_levels.smoke_level(wad, "MAP02", lambda *_: FakeGame())
    assert not result.passed and result.reason == "crash: WadError"


def test_a_held_out_level_is_loaded_and_closed_without_an_episode(tmp_path):
    games = []

    def loader(_wad, _level):
        games.append(FakeGame())
        return games[-1]

    assert smoke_levels.engine_loads(tmp_path / "x.wad", "MAP04", loader).passed
    assert games[0].closed


def test_the_published_file_holds_only_ids_and_labels_and_passes_the_content_gate(tmp_path):
    results = {
        "MAP01": SmokeResult(True, ""),
        "MAP02": SmokeResult(
            False, "no_route: blue door is locked and no blue key exists anywhere"
        ),
        "MAP03": SmokeResult(False, "crash: RuntimeError"),
    }
    document = smoke_levels.publishable(results)
    assert document["levels"] == {"MAP01": "pass", "MAP02": "drop_no_route", "MAP03": "drop_crash"}
    assert document["counts"] == {"pass": 1, "drop": 2}
    target = tmp_path / "results" / "evolve-levels.json"
    target.parent.mkdir()
    target.write_text(json.dumps(document))
    gate = ROOT / "scripts" / "gates" / "check_results_content.py"
    done = subprocess.run(
        [sys.executable, str(gate), str(target)], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_smoke_results_feed_the_split_directly():
    every = {f"MAP{n:02d}": SmokeResult(True, "") for n in range(1, 33)}
    every["MAP12"] = SmokeResult(False, "no_route: x")
    assert "MAP12" not in EvolveSplit.of(every).held_out
