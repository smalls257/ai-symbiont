"""MoveRun typing: every move the parser can produce has exactly one kind."""

import pytest

from symbiont.act1.goto import GoTo
from symbiont.act1.moves import OpenDoor, RetreatTo, ShootNearest, Turn, WalkTo
from symbiont.act1.steplog import MoveKind, kind_of


def test_kind_of_maps_every_move_type():
    assert kind_of(WalkTo("Banana")) == MoveKind.WALK
    assert kind_of(RetreatTo("Banana")) == MoveKind.WALK
    assert kind_of(GoTo("door", None)) == MoveKind.WALK
    assert kind_of(Turn(90.0)) == MoveKind.TURN
    assert kind_of(ShootNearest()) == MoveKind.SHOOT
    assert kind_of(OpenDoor()) == MoveKind.USE
    with pytest.raises(TypeError):
        kind_of(object())
