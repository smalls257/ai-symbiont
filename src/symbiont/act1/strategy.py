"""Strategy text to moves: strict parsing of the model's reply.

An unknown move raises `StrategyError` and never falls back to a default such as "explore", so a
model that invents a move is visible as an invalid reply rather than hidden behind a guess.
"""

import re

from symbiont.act1.goto import GoTo
from symbiont.act1.moves import DOOR_NAMES, OpenDoor, RetreatTo, ShootNearest, Turn, WalkTo
from symbiont.act1.navmap import NavMap


class StrategyError(ValueError):
    """The model's reply is not a valid strategy."""


Move = WalkTo | RetreatTo | Turn | ShootNearest | OpenDoor | GoTo

_CALL = re.compile(r"^(?P<name>[A-Za-z_]\w*)\((?P<arg>[^()]*)\)$")


def _object_argument(name: str, arg: str) -> str:
    target = arg.strip()
    if not target or "," in target:
        raise StrategyError(f"{name} takes exactly one object name, got {arg!r}")
    return target


def _degrees_argument(arg: str) -> float:
    try:
        return float(arg.strip())
    except ValueError:
        raise StrategyError(f"turn takes a number of degrees, got {arg!r}") from None


def _parse_move(statement: str, nav: NavMap | None) -> Move:
    match = _CALL.match(statement)
    if match is None:
        raise StrategyError(f"not a move call: {statement!r}")
    name, arg = match["name"], match["arg"]
    if name == "walk_to":
        return WalkTo(_object_argument(name, arg))
    if name == "retreat_to":
        return RetreatTo(_object_argument(name, arg))
    if name == "go_to":
        return GoTo(_object_argument(name, arg), nav)
    if name == "turn":
        return Turn(_degrees_argument(arg))
    if name == "open_door":
        if arg.strip().lower() not in ("", *DOOR_NAMES):
            raise StrategyError(f"open_door takes no argument or 'door', got {arg!r}")
        return OpenDoor()
    if name == "shoot_nearest":
        if arg.strip():
            raise StrategyError(f"shoot_nearest takes no argument, got {arg!r}")
        return ShootNearest()
    raise StrategyError(
        f"unknown move {name!r}; "
        "allowed: walk_to, go_to, turn, shoot_nearest, retreat_to, open_door"
    )


def parse_strategy(text: str, nav: NavMap | None = None) -> list[Move]:
    """One move per line (or separated by `;`). Raises StrategyError on anything else.

    `nav` is the level's map for go_to; without it go_to stops saying so rather than guessing.
    """
    statements = [s.strip() for s in re.split(r"[\n;]", text) if s.strip()]
    if not statements:
        raise StrategyError("empty strategy")
    return [_parse_move(s, nav) for s in statements]
