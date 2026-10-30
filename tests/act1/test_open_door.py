import pytest

from symbiont.act1.env_text import GameStateView, Layout, SeenDoor
from symbiont.act1.moves import Button, Done, OpenDoor, WalkTo
from symbiont.act1.strategy import StrategyError, parse_strategy

OPEN = Layout(True, True, True, False)


def view(doors=(), reach=(), keys=()) -> GameStateView:
    return GameStateView(
        health=100,
        ammo=10,
        position=(0.0, 0.0),
        angle_deg=0.0,
        objects=(),
        doors=tuple(doors),
        keys_held=tuple(keys),
        layout=OPEN,
        reach_doors=tuple(reach),
    )


NEAR = SeenDoor(30.0, 2.0)


def test_open_door_walks_to_the_door_first():
    assert OpenDoor().step(view(doors=[SeenDoor(300.0, 0.0)])) == frozenset({Button.FORWARD})
    assert OpenDoor().step(view(doors=[SeenDoor(300.0, 40.0)])) == frozenset({Button.TURN_LEFT})


def test_open_door_presses_use_then_reports_opened_when_door_is_gone():
    move = OpenDoor()
    assert move.step(view(doors=[NEAR], reach=[NEAR])) == frozenset({Button.USE})
    assert move.step(view(reach=[])) == Done("opened")


def test_open_door_turns_to_face_an_in_reach_door_that_is_off_screen_before_pressing_use():
    behind = SeenDoor(30.0, 120.0)
    assert OpenDoor().step(view(reach=[behind])) == frozenset({Button.TURN_LEFT})
    assert OpenDoor().step(view(reach=[SeenDoor(30.0, -120.0)])) == frozenset({Button.TURN_RIGHT})
    assert OpenDoor().step(view(reach=[SeenDoor(30.0, 3.0)])) == frozenset({Button.USE})


def test_open_door_turning_toward_an_unreachable_bearing_is_bounded_by_its_tic_budget():
    move = OpenDoor()
    stuck = view(reach=[SeenDoor(30.0, 120.0)])  # the stub never turns, so the door stays behind
    result = run_to_verdict(move, stuck)
    assert isinstance(result, Done) and result.reason.startswith("did not open")
    assert "never faced" in result.reason


def test_open_door_reports_no_door_in_reach_without_pressing_use():
    assert OpenDoor().step(view()) == Done("no door in reach")


def run_to_verdict(move, state):
    result = None
    for _ in range(OpenDoor.max_tics):
        result = move.step(state)
        if isinstance(result, Done):
            return result
    return result


def test_open_door_reports_locked_with_the_static_key_colour_after_trying():
    blue = SeenDoor(30.0, 2.0, key_colour="blue")
    move = OpenDoor()
    assert move.step(view(doors=[blue], reach=[blue])) == frozenset(
        {Button.USE}
    )  # it does try the door
    assert run_to_verdict(move, view(doors=[blue], reach=[blue])) == Done("locked: needs blue key")


def test_open_door_with_the_key_in_hand_does_not_claim_locked():
    blue = SeenDoor(30.0, 2.0, key_colour="blue")
    result = run_to_verdict(OpenDoor(), view(doors=[blue], reach=[blue], keys=["blue"]))
    assert result.reason.startswith("did not open")
    assert "keys held: blue" in result.reason


def test_open_door_reports_did_not_open_visibly_for_a_stuck_plain_door():
    result = run_to_verdict(OpenDoor(), view(doors=[NEAR], reach=[NEAR]))
    assert result.reason.startswith("did not open")


def test_open_door_label_is_scripted_and_parser_accepts_it():
    moves = parse_strategy("open_door(door)")
    assert isinstance(moves[0], OpenDoor)
    assert moves[0].label == "scripted open_door()"
    assert [type(m) for m in parse_strategy("open_door()\nwalk_to(door)")] == [OpenDoor, WalkTo]


def test_parser_still_rejects_unknown_moves_with_open_door_in_the_list():
    with pytest.raises(StrategyError, match="unlock"):
        parse_strategy("open_door()\nunlock()")
    with pytest.raises(StrategyError):
        parse_strategy("open_door(a, b)")


def test_open_door_with_the_right_key_object_held_never_says_it_needs_that_key():
    blue = SeenDoor(30.0, 2.0, key_colour="blue")
    result = run_to_verdict(OpenDoor(), view(doors=[blue], reach=[blue], keys=["BlueCard"]))
    assert result.reason.startswith("did not open") and "needs" not in result.reason


def test_open_door_without_the_key_object_says_which_colour_it_needs():
    blue = SeenDoor(30.0, 2.0, key_colour="blue")
    result = run_to_verdict(OpenDoor(), view(doors=[blue], reach=[blue], keys=["RedCard"]))
    assert result == Done("locked: needs blue key")


def test_open_door_marks_success_with_a_typed_flag_not_only_text():
    move = OpenDoor()
    move.step(view(doors=[NEAR], reach=[NEAR]))
    result = move.step(view(reach=[]))
    assert result.succeeded and not Done("opened").succeeded
