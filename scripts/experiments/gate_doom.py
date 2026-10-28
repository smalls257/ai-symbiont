"""Freedoom items for the reasoning-strength gate: the route oracle and the reply scorer (pure).

Violation prevented: Paper Tiger. The oracle is the repo's own route finder (`route_hints`), not
a judgment call: the best next action is fixed by the map before any model is asked.
"""

from dataclasses import dataclass

from symbiont.act1.env_text import GameStateView, RouteHint
from symbiont.act1.glimmer import Reply
from symbiont.act1.goto import GoTo
from symbiont.act1.moves import WalkTo
from symbiont.act1.strategy import StrategyError, parse_strategy


@dataclass(frozen=True)
class DoomOracle:
    """What the route finder says to do next: a kind, and the go_to targets that mean it."""

    kind: str  # exit | key | door
    go_to_targets: frozenset[str]
    walk_to_targets: frozenset[str]  # only what is in view right now


def _reachable(routes: tuple[RouteHint, ...], kind: str) -> RouteHint | None:
    return next((r for r in routes if r.kind == kind and r.path_units is not None), None)


def oracle_for(state: GameStateView) -> DoomOracle | None:
    """Exit if a route exists, else the nearest key, else the nearest closed door, else None."""
    exit_hint = _reachable(state.routes, "exit")
    if exit_hint is not None:
        return DoomOracle("exit", frozenset({"exit"}), frozenset({"exit"} if state.exits else ()))
    key_hint = _reachable(state.routes, "key")
    if key_hint is not None:
        label = key_hint.label.lower()
        return DoomOracle("key", frozenset({"key", label}), frozenset({label}))
    door_hint = _reachable(state.routes, "door")
    if door_hint is not None:
        return DoomOracle("door", frozenset({"door"}), frozenset({"door"} if state.doors else ()))
    return None


def score_doom_reply(reply: Reply, oracle: DoomOracle) -> str:
    """Label of the first move: success, wrong_move, invalid or truncated. Never a default."""
    if reply.finish_reason == "length":
        return "truncated"
    try:
        first = parse_strategy(reply.text)[0]
    except StrategyError:
        return "invalid"
    if isinstance(first, GoTo) and first.target.lower() in oracle.go_to_targets:
        return "success"
    if isinstance(first, WalkTo) and first.target.lower() in oracle.walk_to_targets:
        return "success"
    return "wrong_move"
