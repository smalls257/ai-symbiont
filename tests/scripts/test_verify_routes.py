"""The route verifier plays the engine, so it must refuse a held-out level before anything else."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import verify_routes  # noqa: E402 - needs the scripts path added above

from symbiont.act1.levels import HeldOutLevelError, LevelSplit, levels_in  # noqa: E402


@pytest.mark.parametrize("level", levels_in(LevelSplit.HELD_OUT))
def test_the_walker_refuses_every_held_out_level_before_it_reads_a_wad(level, tmp_path):
    with pytest.raises(HeldOutLevelError):
        verify_routes.verify_level(tmp_path / "no-such.wad", level)


def test_the_default_levels_are_the_training_levels():
    assert verify_routes.default_levels() == list(levels_in(LevelSplit.TRAINING))
