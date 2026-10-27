from symbiont.act1.env_text import GameStateView, Layout, SeenObject
from symbiont.act1.episode import build_prompt, execute_move
from symbiont.act1.moves import Button, Turn, WalkTo

OPEN = Layout(True, True, True, False)


def view(objects=(), angle=0.0) -> GameStateView:
    return GameStateView(100, 10, (0.0, 0.0), angle, tuple(objects), (), (), OPEN)


def test_execute_move_feeds_back_state_until_done():
    angles = iter([0.0, 30.0, 60.0, 88.0])
    pressed = []
    outcome = execute_move(
        Turn(90.0),
        observe=lambda: view(angle=next(angles)),
        act=pressed.append,
    )
    assert pressed == [frozenset({Button.TURN_LEFT})] * 3
    assert outcome == "turned 90 degrees"


def test_execute_move_times_out_loudly():
    outcome = execute_move(
        WalkTo("BlueCard"),
        observe=lambda: view([SeenObject("BlueCard", 500.0, 0.0)]),
        act=lambda buttons: None,
    )
    assert outcome == f"timeout after {WalkTo.max_tics} tics"


def test_execute_move_reports_episode_end():
    outcome = execute_move(WalkTo("BlueCard"), observe=lambda: None, act=lambda buttons: None)
    assert outcome == "episode ended"


def test_prompt_labels_moves_scripted_and_lists_the_vocabulary():
    prompt = build_prompt("Player: health 100.", history=["scripted turn(90) -> turned 90 degrees"])
    for name in ("walk_to", "turn", "shoot_nearest", "retreat_to"):
        assert name in prompt
    assert "scripted" in prompt
    assert "Player: health 100." in prompt
    assert "turned 90 degrees" in prompt
