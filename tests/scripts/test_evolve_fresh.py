"""The exploratory fresh-map run: seed-major cases and the listed-maps-only mode."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import fresh_onemove as fm  # noqa: E402 - needs the scripts path added above
import play_case as pc  # noqa: E402

pytestmark = pytest.mark.periphery


def test_cases_are_seed_major():
    cases = fm.fresh_cases(["OB0101", "OB0102"], seeds=2)
    assert [(c.level, c.seed) for c in cases] == [
        ("OB0101", 4101), ("OB0102", 4101), ("OB0101", 4102), ("OB0102", 4102),
    ]  # fmt: skip


def test_listed_mode_allows_listed_maps_and_refuses_others(tmp_path):
    setup = pc.EngineSetup(
        wad=tmp_path, episodes=tmp_path, mode=pc.RunMode.EXPLORATORY_LISTED,
        final_levels=frozenset({"OB0101"}),
    )  # fmt: skip
    player = pc.EnginePlayer(lambda _card, _case: None, setup)
    player._require_allowed("OB0101")
    with pytest.raises(pc.NotInFinalTestError):
        player._require_allowed("OB0999")
