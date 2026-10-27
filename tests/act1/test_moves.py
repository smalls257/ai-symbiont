import pytest

from symbiont.act1.env_text import GameStateView, Layout, SeenObject
from symbiont.act1.moves import (
    Button,
    Done,
    OpenDoor,
    RetreatTo,
    ShootNearest,
    Turn,
    WalkTo,
)
from symbiont.act1.strategy import StrategyError, parse_strategy

OPEN = Layout(True, True, True, False)
WALLED = Layout(True, False, True, True)


def state(objects=(), angle=0.0, layout=OPEN, ammo=10) -> GameStateView:
    return GameStateView(
        health=100,
        ammo=ammo,
        position=(0.0, 0.0),
        angle_deg=angle,
        objects=tuple(objects),
        doors=(),
        keys_held=(),
        layout=layout,
    )


def test_strategy_parse_rejects_unknown_move():
    with pytest.raises(StrategyError, match="explore"):
        parse_strategy("explore()")
    with pytest.raises(StrategyError):
        parse_strategy("walk_to(BlueCard)\nrun_away()")


def test_strategy_parse_rejects_empty_and_bad_arguments():
    for bad in ("", "   ", "turn(abc)", "turn()", "walk_to()", "shoot_nearest(3)", "walk_to(a, b)"):
        with pytest.raises(StrategyError):
            parse_strategy(bad)


def test_strategy_parse_reads_known_moves_in_order():
    moves = parse_strategy("walk_to(BlueCard)\nturn(-90)\nshoot_nearest()\nretreat_to(Door)")
    assert [type(m) for m in moves] == [WalkTo, Turn, ShootNearest, RetreatTo]
    assert moves[0].target == "BlueCard"
    assert moves[1].degrees == -90.0
    assert moves[0].label.startswith("scripted ")


def test_strategy_parse_accepts_semicolons():
    assert len(parse_strategy(" turn(45) ; shoot_nearest() ")) == 2


def test_walk_to_turns_toward_target_then_advances_then_arrives():
    move = WalkTo("BlueCard")
    left = state([SeenObject("BlueCard", 300.0, 40.0)])
    assert move.step(left) == frozenset({Button.TURN_LEFT})
    right = state([SeenObject("BlueCard", 300.0, -40.0)])
    assert move.step(right) == frozenset({Button.TURN_RIGHT})
    ahead = state([SeenObject("BlueCard", 300.0, 2.0)])
    assert move.step(ahead) == frozenset({Button.FORWARD})
    arrived = state([SeenObject("BlueCard", 30.0, 2.0)])
    assert move.step(arrived) == Done("arrived at BlueCard")


def test_walk_to_reports_target_not_visible_and_blocked():
    assert WalkTo("BlueCard").step(state()) == Done("BlueCard not visible")
    blocked = state([SeenObject("BlueCard", 300.0, 0.0)], layout=WALLED)
    assert isinstance(WalkTo("BlueCard").step(blocked), Done)


def test_turn_uses_angle_feedback_and_finishes():
    move = Turn(90.0)
    assert move.step(state(angle=0.0)) == frozenset({Button.TURN_LEFT})
    assert move.step(state(angle=60.0)) == frozenset({Button.TURN_LEFT})
    assert isinstance(move.step(state(angle=88.0)), Done)


def test_turn_wraps_around_360():
    move = Turn(-90.0)
    assert move.step(state(angle=10.0)) == frozenset({Button.TURN_RIGHT})
    assert move.step(state(angle=300.0)) == frozenset(
        {Button.TURN_RIGHT}
    )  # target 280; 300 is still short
    assert isinstance(move.step(state(angle=281.0)), Done)


def test_shoot_nearest_aims_then_fires_nearest_enemy():
    move = ShootNearest()
    scene = [SeenObject("Zombieman", 400.0, 0.0), SeenObject("Imp", 150.0, 25.0)]
    assert move.step(state(scene)) == frozenset({Button.TURN_LEFT})
    aimed = [SeenObject("Zombieman", 400.0, 0.0), SeenObject("Imp", 150.0, 1.0)]
    assert move.step(state(aimed)) == frozenset({Button.ATTACK})


def test_shoot_nearest_stops_without_enemy_or_ammo():
    assert ShootNearest().step(state([SeenObject("BlueCard", 50.0, 0.0)])) == Done(
        "no enemy visible"
    )
    assert ShootNearest().step(state([SeenObject("Imp", 50.0, 0.0)], ammo=0)) == Done("out of ammo")


def test_retreat_to_goes_to_target_and_backs_away_from_close_enemy():
    move = RetreatTo("Shotgun")
    assert move.step(state([SeenObject("Shotgun", 200.0, 0.0)])) == frozenset({Button.FORWARD})
    assert isinstance(move.step(state([SeenObject("Shotgun", 20.0, 0.0)])), Done)
    # Exit is behind us and an enemy is close ahead: back off rather than turn into it.
    scene = [SeenObject("Shotgun", 200.0, 170.0), SeenObject("Imp", 80.0, 0.0)]
    assert move.step(state(scene)) == frozenset({Button.BACKWARD})
    assert move.label.startswith("scripted ")


def test_walk_to_can_target_a_door_by_name():
    from symbiont.act1.env_text import SeenDoor

    scene = GameStateView(100, 10, (0.0, 0.0), 0.0, (), (SeenDoor(300.0, 30.0),), (), OPEN)
    for name in ("door", "closed door", "Door"):
        assert WalkTo(name).step(scene) == frozenset({Button.TURN_LEFT})


def test_walk_to_can_target_the_exit_by_name():
    from symbiont.act1.env_text import SeenExit

    scene = GameStateView(
        100, 10, (0.0, 0.0), 0.0, (), (), (), OPEN, exits=(SeenExit(300.0, -30.0),)
    )
    assert WalkTo("exit").step(scene) == frozenset({Button.TURN_RIGHT})
    assert WalkTo("exit").step(state()) == Done("exit not visible")


def test_walking_to_a_door_is_not_blocked_by_the_door_itself():
    from symbiont.act1.env_text import SeenDoor

    scene = GameStateView(100, 10, (0.0, 0.0), 0.0, (), (SeenDoor(120.0, 0.0),), (), WALLED)
    assert WalkTo("door").step(scene) == frozenset({Button.FORWARD})
    assert OpenDoor().step(scene) == frozenset({Button.FORWARD})
