"""Cheap seeded policies that drive the episode loop like a model does.

A log needs many episodes and a model call per episode is too slow; these replies pass the same
strict parser, so every logged move is real. Only seeded `random.Random` instances are used,
never the global RNG, so a seed reproduces a run.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass

from symbiont.act1.glimmer import Reply, ReplyFn

RANDOM_MENU = (
    "go_to(door)",
    "go_to(exit)",
    "go_to(key)",
    "open_door()",
    "turn(90)",
    "turn(-90)",
    "turn(180)",
    "shoot_nearest()",
)
EXPLORER_CYCLE = ("go_to(key)", "open_door()", "go_to(door)", "turn(90)", "go_to(exit)")
# The opening turn is 45 * k degrees so seeds start facing different ways.
_OPENING_STEPS = (1, 7)
_OPENING_DEGREES = 45
_MOST_RANDOM_LINES = 3


@dataclass(frozen=True)
class Policy:
    """A named reply function; the name goes into session ids and the policy tag."""

    name: str
    reply: ReplyFn


def _stop_reply(text: str) -> Reply:
    """A finished model reply with the given text."""
    return Reply(text=text, finish_reason="stop", reasoning_chars=0)


def random_policy(seed: int) -> Policy:
    """The floor: one to three menu moves per call, no regard for the state."""
    rng = random.Random(seed)

    def reply(_prompt: str) -> Reply:
        """A random reply of 1 to _MOST_RANDOM_LINES menu lines."""
        count = rng.randint(1, _MOST_RANDOM_LINES)
        return _stop_reply("\n".join(rng.choice(RANDOM_MENU) for _ in range(count)))

    return Policy("random", reply)


def scripted_explorer(seed: int) -> Policy:
    """A seeded opening turn, then the same cycle forever, so its episodes are comparable."""
    degrees = _OPENING_DEGREES * random.Random(seed).randint(*_OPENING_STEPS)
    opening = f"turn({degrees})"
    calls = 0

    def reply(_prompt: str) -> Reply:
        """The opening, then the explorer cycle in order."""
        nonlocal calls
        calls += 1
        if calls == 1:
            return _stop_reply(opening)
        return _stop_reply(EXPLORER_CYCLE[(calls - 2) % len(EXPLORER_CYCLE)])

    return Policy("scripted_explorer", reply)


_POLICIES: dict[str, Callable[[int], Policy]] = {
    "random": random_policy,
    "scripted_explorer": scripted_explorer,
}


def policy_named(name: str, seed: int) -> Policy:
    """Raises ValueError for an unknown name rather than choosing a default policy."""
    if name not in _POLICIES:
        raise ValueError(f"unknown policy {name!r}; allowed: {', '.join(_POLICIES)}")
    return _POLICIES[name](seed)
