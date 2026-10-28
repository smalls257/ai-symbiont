"""The room lookup: which map sector holds a point."""

import pytest

from room_world import two_rooms_with_a_pillar
from symbiont.act1.rooms import RoomFinder, RoomLookupError


def test_room_at_names_the_sector_holding_the_point():
    rooms = RoomFinder(two_rooms_with_a_pillar())
    assert rooms.room_at((20.0, 20.0)) == 0
    assert rooms.room_at((150.0, 50.0)) == 1


def test_a_point_inside_an_inner_sector_belongs_to_it_not_the_room_around_it():
    assert RoomFinder(two_rooms_with_a_pillar()).room_at((50.0, 50.0)) == 2


def test_a_point_outside_every_sector_raises_naming_the_point():
    with pytest.raises(RoomLookupError, match="500, 500"):
        RoomFinder(two_rooms_with_a_pillar()).room_at((500.0, 500.0))


def test_a_point_on_the_line_between_two_rooms_resolves_to_one_of_them():
    assert RoomFinder(two_rooms_with_a_pillar()).room_at((100.0, 50.0)) in (0, 1)


def test_a_point_on_a_horizontal_pillar_edge_resolves_to_one_sector():
    assert RoomFinder(two_rooms_with_a_pillar()).room_at((50.0, 40.0)) in (0, 2)
