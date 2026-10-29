"""The training / held-out level split."""

import pytest

from symbiont.act1.levels import (
    HeldOutLevelError,
    LevelSplit,
    Project,
    UnknownLevelError,
    levels_in,
    project_of,
    require_training,
    split_of,
)


def test_every_fourth_map_is_held_out_and_the_rest_train():
    held_out = levels_in(LevelSplit.HELD_OUT)
    assert held_out == ("MAP04", "MAP08", "MAP12", "MAP16", "MAP20", "MAP24", "MAP28", "MAP32")
    assert len(levels_in(LevelSplit.TRAINING)) == 24
    assert set(held_out).isdisjoint(levels_in(LevelSplit.TRAINING))


def test_map01_trains_because_development_runs_played_it():
    assert split_of("MAP01") == LevelSplit.TRAINING


@pytest.mark.parametrize(
    "level", ["MAP00", "MAP33", "E0M1", "E5M1", "E1M0", "E1M10", "EAMB", "map04", "MAP4", ""]
)
def test_a_level_outside_the_wad_raises(level):
    with pytest.raises(UnknownLevelError):
        split_of(level)


def test_require_training_refuses_a_held_out_level_by_name():
    with pytest.raises(HeldOutLevelError, match="MAP08"):
        require_training("MAP08")
    require_training("MAP07")  # no error


def test_phase_one_holds_out_every_fourth_map_in_play_order():
    held_out = levels_in(LevelSplit.HELD_OUT, Project.FREEDOOM1)
    assert held_out == ("E1M4", "E1M8", "E2M3", "E2M7", "E3M2", "E3M6", "E4M1", "E4M5", "E4M9")
    assert len(levels_in(LevelSplit.TRAINING, Project.FREEDOOM1)) == 27
    assert project_of("E3M2") == Project.FREEDOOM1 and project_of("MAP05") == Project.FREEDOOM2


def test_phase_one_held_out_maps_are_refused_by_name():
    with pytest.raises(HeldOutLevelError, match="E2M3"):
        require_training("E2M3")
    require_training("E2M2")
