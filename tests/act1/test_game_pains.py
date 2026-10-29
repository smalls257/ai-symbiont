"""Game pain tags: each fires on the event it names and stays silent on a near miss."""

from room_world import two_rooms_with_a_pillar
from symbiont.act1.env_text import GameStateView, Layout, SeenDoor, SeenExit, SeenObject
from symbiont.act1.game_pains import GamePain, tag_pains
from symbiont.act1.rooms import RoomFinder
from symbiont.act1.steplog import MoveKind, MoveRun

ROOMS = RoomFinder(two_rooms_with_a_pillar())
IN_ROOM_0 = (10.0, 10.0)
ELSEWHERE_IN_ROOM_0 = (20.0, 80.0)
IN_ROOM_1 = (150.0, 50.0)
BLUE_CARD = SeenObject("BlueCard", 50.0, 0.0)


def view(
    position, angle=0.0, objects=(), health=100.0, doors=(), exits=(), keys=(), closed=(), ammo=50.0
):
    return GameStateView(
        health=health,
        ammo=ammo,
        position=position,
        angle_deg=angle,
        objects=tuple(objects),
        doors=tuple(doors),
        keys_held=tuple(keys),
        layout=Layout(True, True, True, False),
        exits=tuple(exits),
        closed_sectors=frozenset(closed),
    )


def run(before, after, kind=MoveKind.WALK, outcome="arrived", tics=10):
    return MoveRun(0, "move", kind, outcome, tics, before, after)


def tags(*runs):
    return tag_pains(list(runs), ROOMS)


def test_wall_bump_fires_on_a_walk_blocked_by_a_wall():
    blocked = run(
        view(IN_ROOM_0), view((30.0, 10.0)), outcome="blocked by a wall on the way to BlueCard"
    )
    assert GamePain.WALL_BUMP in tags(blocked)[0]


def test_wall_bump_fires_on_a_go_to_stuck_on_its_route():
    stuck = run(view(IN_ROOM_0), view((30.0, 10.0)), outcome="stuck at 12,34 on the way to door")
    assert GamePain.WALL_BUMP in tags(stuck)[0]


def test_wall_bump_silent_when_the_target_went_out_of_view():
    lost = run(view(IN_ROOM_0), view((30.0, 10.0)), outcome="BlueCard not visible")
    assert GamePain.WALL_BUMP not in tags(lost)[0]


def test_wall_bump_silent_at_a_locked_door():
    locked = run(
        view(IN_ROOM_0),
        view((30.0, 10.0)),
        outcome="stopped at door 40 ahead: locked: needs blue key",
    )
    assert GamePain.WALL_BUMP not in tags(locked)[0]


def test_enemy_in_the_way_is_not_a_wall_bump():
    stopped = run(
        view(IN_ROOM_0), view((30.0, 10.0)), outcome="enemy in the way: Zombieman at 37", tics=5
    )
    assert GamePain.WALL_BUMP not in tags(stopped)[0]


def test_wall_bump_silent_when_the_walk_never_started():
    never = run(
        view(IN_ROOM_0), view(IN_ROOM_0), outcome="blocked by a wall on the way to x", tics=0
    )
    assert GamePain.WALL_BUMP not in tags(never)[0]


def test_room_reentered_fires_on_coming_back_to_a_room_left_earlier():
    out = run(view(IN_ROOM_0), view(IN_ROOM_1))
    back = run(view(IN_ROOM_1), view(IN_ROOM_0))
    first, second = tags(out, back)
    assert GamePain.ROOM_REENTERED not in first
    assert GamePain.ROOM_REENTERED in second


def test_moving_within_one_room_is_not_reentering():
    out = run(view(IN_ROOM_0), view(IN_ROOM_1))
    within = run(view(IN_ROOM_1), view((170.0, 50.0)))
    assert GamePain.ROOM_REENTERED not in tags(out, within)[1]


def test_room_rechecked_fires_on_a_second_turn_that_shows_nothing_new():
    seen = view(IN_ROOM_0, 90.0, [BLUE_CARD])
    first = run(view(IN_ROOM_0), seen, MoveKind.TURN)
    second = run(seen, view(IN_ROOM_0, 180.0, [BLUE_CARD]), MoveKind.TURN)
    assert GamePain.ROOM_RECHECKED in tags(first, second)[1]


def test_room_rechecked_silent_when_the_second_turn_reveals_a_new_object():
    seen = view(IN_ROOM_0, 90.0, [BLUE_CARD])
    more = view(
        IN_ROOM_0, 180.0, [BLUE_CARD], doors=[SeenDoor(30.0, 0.0, "blue")], exits=[SeenExit(9.0, 0)]
    )
    first = run(view(IN_ROOM_0), seen, MoveKind.TURN)
    second = run(seen, more, MoveKind.TURN)
    assert GamePain.ROOM_RECHECKED not in tags(first, second)[1]


def test_first_turn_in_a_room_is_never_a_recheck():
    only = run(view(IN_ROOM_0, 0.0, [BLUE_CARD]), view(IN_ROOM_0, 90.0, [BLUE_CARD]), MoveKind.TURN)
    assert GamePain.ROOM_RECHECKED not in tags(only)[0]


def test_wasted_move_fires_when_nothing_changed():
    idle = run(view(IN_ROOM_0), view((12.0, 10.0), 3.0), MoveKind.USE, "nothing to open")
    assert tags(idle)[0] == (GamePain.WASTED_MOVE,)


def test_wasted_move_silent_when_health_changed():
    hurt = run(view(IN_ROOM_0), view(IN_ROOM_0, health=80.0), MoveKind.USE, "nothing to open")
    assert GamePain.WASTED_MOVE not in tags(hurt)[0]


def test_wasted_move_silent_when_the_player_turned_across_the_wraparound():
    turn = run(view(IN_ROOM_0, 350.0), view(IN_ROOM_0, 80.0), MoveKind.TURN, "turned 90 degrees")
    assert GamePain.WASTED_MOVE not in tags(turn)[0]


def test_wasted_move_fires_on_a_turn_that_wrapped_back_to_the_same_heading():
    idle = run(view(IN_ROOM_0, 359.0), view(IN_ROOM_0, 1.0), MoveKind.TURN, "turned 2 degrees")
    assert GamePain.WASTED_MOVE in tags(idle)[0]


ZOMBIE = SeenObject("Zombieman", 200.0, 0.0)


def test_wasted_move_fires_on_a_shot_with_no_enemy_in_view_even_when_ammo_dropped():
    fired = run(view(IN_ROOM_0), view(IN_ROOM_0, ammo=49.0), MoveKind.SHOOT, "no enemy visible")
    assert GamePain.WASTED_MOVE in tags(fired)[0]


def test_wasted_move_fires_on_a_shot_with_no_enemy_in_view_even_when_health_changed():
    hurt = run(view(IN_ROOM_0), view(IN_ROOM_0, health=80.0), MoveKind.SHOOT, "shot")
    assert GamePain.WASTED_MOVE in tags(hurt)[0]


def test_wasted_move_silent_on_a_shot_that_missed_a_visible_enemy():
    missed = run(
        view(IN_ROOM_0, objects=[ZOMBIE]),
        view(IN_ROOM_0, objects=[ZOMBIE], ammo=49.0),
        MoveKind.SHOOT,
        "timeout after 60 tics",
    )
    assert GamePain.WASTED_MOVE not in tags(missed)[0]


def test_a_move_that_ended_the_episode_gets_no_tags():
    died = run(view(IN_ROOM_0), None, outcome="blocked by a wall on the way to x")
    assert tags(died) == [()]


def test_tags_are_one_tuple_per_run():
    walk = run(view(IN_ROOM_0), view(ELSEWHERE_IN_ROOM_0))
    assert tags(walk, walk, walk) == [(), (), ()]
    assert tags() == []
