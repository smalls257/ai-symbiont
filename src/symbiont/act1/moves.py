"""Scripted moves: the model picks a strategy from text, these execute it.

Every move is scripted, not learned, and says so in its `label` so any log or
demo shows "scripted walk_to(BlueCard)". A move is a function of the
current `GameStateView` (plus, for `Turn`, the target angle it fixed on its first step, so
move instances are single-use): `step(state)` returns the buttons to hold for one tic,
or `Done(reason)`. Parsing lives in strategy.py; go_to (route-following) in goto.py.
"""

from dataclasses import dataclass, field
from enum import Enum

from symbiont.act1.env_text import GameStateView, SeenObject, normalize_degrees
from symbiont.act1.navtypes import held_colours


class Button(Enum):
    """A game button a move may hold for one tic."""

    FORWARD = "forward"
    BACKWARD = "backward"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    ATTACK = "attack"
    USE = "use"


@dataclass(frozen=True)
class Done:
    """A move finished; `reason` is what the model reads back in its history."""

    reason: str
    # A typed outcome for callers that must branch on success (OpenDoor "opened"); not part of
    # equality.
    succeeded: bool = field(default=False, compare=False)


Action = frozenset[Button]
StepResult = Action | Done

TURN_TOLERANCE_DEG = 6.0
FACING_TOLERANCE_DEG = 10.0
AIM_TOLERANCE_DEG = 4.0
WALK_ARRIVAL_UNITS = 48.0
RETREAT_ARRIVAL_UNITS = 24.0
DANGER_UNITS = 128.0
DANGER_CONE_DEG = 45.0
BEHIND_DEG = 90.0


def hold(*buttons: Button) -> Action:
    """The set of buttons to hold for one tic."""
    return frozenset(buttons)


def turn_toward(bearing_deg: float) -> Action:
    """Turn left for a positive bearing, right otherwise."""
    return hold(Button.TURN_LEFT if bearing_deg > 0 else Button.TURN_RIGHT)


DOOR_NAMES = frozenset({"door", "closed door"})


def find_visible(state: GameStateView, name: str) -> SeenObject | None:
    """Nearest visible object with this name; "door" names resolve to the nearest listed door."""
    if name.lower() == "exit":
        exits = [SeenObject("exit", e.distance, e.bearing_deg) for e in state.exits]
        return min(exits, key=lambda seen: seen.distance, default=None)
    if name.lower() in DOOR_NAMES:
        doors = [SeenObject("door", d.distance, d.bearing_deg) for d in state.doors]
        return min(doors, key=lambda seen: seen.distance, default=None)
    matches = [seen for seen in state.objects if seen.name.lower() == name.lower()]
    return min(matches, key=lambda seen: seen.distance, default=None)


def _approach(state: GameStateView, target: SeenObject, arrival: float) -> StepResult:
    if target.distance <= arrival:
        return Done(f"arrived at {target.name}")
    if abs(target.bearing_deg) > FACING_TOLERANCE_DEG:
        return turn_toward(target.bearing_deg)
    if state.layout.wall_close_ahead and target.name not in ("door", "exit"):
        # A door or exit is itself the wall in front; only other targets are blocked by one.
        return Done(f"blocked by a wall on the way to {target.name}")
    return hold(Button.FORWARD)


@dataclass
class WalkTo:
    """Walk toward a visible object, door or exit."""

    target: str
    max_tics = 120

    @property
    def label(self) -> str:
        """Names the move as scripted in every log line."""
        return f"scripted walk_to({self.target})"

    def step(self, state: GameStateView) -> StepResult:
        """Buttons for one tic, or Done when arrived, blocked or the target is out of view."""
        found = find_visible(state, self.target)
        if found is None:
            return Done(f"{self.target} not visible")
        return _approach(state, found, WALK_ARRIVAL_UNITS)


@dataclass
class RetreatTo:
    """Go to a safe spot, backing off rather than turning into a close enemy."""

    target: str
    max_tics = 120

    @property
    def label(self) -> str:
        """Names the move as scripted in every log line."""
        return f"scripted retreat_to({self.target})"

    def step(self, state: GameStateView) -> StepResult:
        """Buttons for one tic; backs off rather than turning into a close enemy."""
        found = find_visible(state, self.target)
        if found is None:
            return Done(f"{self.target} not visible")
        if found.distance <= RETREAT_ARRIVAL_UNITS:
            return Done(f"arrived at {found.name}")
        if abs(found.bearing_deg) > BEHIND_DEG and self._enemy_close_ahead(state):
            return hold(Button.BACKWARD)
        return _approach(state, found, RETREAT_ARRIVAL_UNITS)

    @staticmethod
    def _enemy_close_ahead(state: GameStateView) -> bool:
        return any(
            seen.is_enemy
            and seen.distance <= DANGER_UNITS
            and abs(seen.bearing_deg) <= DANGER_CONE_DEG
            for seen in state.objects
        )


@dataclass
class Turn:
    """Turn by a fixed angle, fixed on the first step."""

    degrees: float
    max_tics = 60
    _target_angle: float | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def label(self) -> str:
        """Names the move as scripted in every log line."""
        return f"scripted turn({self.degrees:g})"

    def step(self, state: GameStateView) -> StepResult:
        """Buttons for one tic, or Done within tolerance of the target angle."""
        if self._target_angle is None:
            self._target_angle = state.angle_deg + self.degrees
        remaining = normalize_degrees(self._target_angle - state.angle_deg)
        if abs(remaining) <= TURN_TOLERANCE_DEG:
            return Done(f"turned {self.degrees:g} degrees")
        return turn_toward(remaining)


@dataclass
class ShootNearest:
    """Aim at and shoot the nearest visible enemy."""

    max_tics = 60

    @property
    def label(self) -> str:
        """Names the move as scripted in every log line."""
        return "scripted shoot_nearest()"

    def step(self, state: GameStateView) -> StepResult:
        """Buttons for one tic, or Done when no enemy is visible or ammo is out."""
        enemies = [seen for seen in state.objects if seen.is_enemy]
        if not enemies:
            return Done("no enemy visible")
        if state.ammo <= 0:
            return Done("out of ammo")
        nearest = min(enemies, key=lambda seen: seen.distance)
        if abs(nearest.bearing_deg) > AIM_TOLERANCE_DEG:
            return turn_toward(nearest.bearing_deg)
        return hold(Button.ATTACK)


USE_TICS = 24


@dataclass
class OpenDoor:
    """Walk to the nearest door, press USE, and say what happened: opened, locked, or did not open.

    The result comes from the world, not from the keypress: "opened" means no closed door is left in
    reach after USE. A door that stays shut and needs a key the player does not hold is "locked",
    with the colour from the map's own linedef special (the engine offers no message API).
    """

    max_tics = 150
    _used_tics: int = field(default=0, init=False, repr=False, compare=False)
    _approach_tics: int = field(default=0, init=False, repr=False, compare=False)

    @property
    def label(self) -> str:
        """Names the move as scripted in every log line."""
        return "scripted open_door()"

    def step(self, state: GameStateView) -> StepResult:
        """Approach, press USE, then judge the outcome from the world."""
        if self._used_tics == 0:
            self._approach_tics += 1
            if self._approach_tics > self.max_tics - USE_TICS:
                return Done(
                    f"did not open: never faced or reached the door "
                    f"within {self.max_tics - USE_TICS} tics"
                )
            return self._approach_door(state)
        if not state.reach_doors:
            return Done("opened", succeeded=True)
        if self._used_tics >= USE_TICS:
            return self._verdict_for_shut_door(state)
        return self._press_use()

    @staticmethod
    def _verdict_for_shut_door(state: GameStateView) -> Done:
        colour = state.reach_doors[0].key_colour
        if colour and colour not in held_colours(state.keys_held):
            return Done(f"locked: needs {colour} key")
        held = ", ".join(state.keys_held) or "none"
        return Done(f"did not open: door stayed shut (keys held: {held})")

    def _approach_door(self, state: GameStateView) -> StepResult:
        if not state.doors and not state.reach_doors:
            return Done("no door in reach")
        if state.reach_doors and (
            not state.doors or state.reach_doors[0].distance <= WALK_ARRIVAL_UNITS
        ):
            nearest = state.reach_doors[0]
            if abs(nearest.bearing_deg) > FACING_TOLERANCE_DEG:
                return turn_toward(nearest.bearing_deg)  # USE only acts on what the player faces
            return self._press_use()
        door = find_visible(state, "door")
        if door is None:
            return Done("no door in reach")
        outcome = _approach(state, door, WALK_ARRIVAL_UNITS)
        if isinstance(outcome, Done):
            if outcome.reason.startswith("arrived"):
                return self._press_use()
            return Done(f"no door in reach: {outcome.reason}")
        return outcome

    def _press_use(self) -> Action:
        self._used_tics += 1
        return hold(Button.USE) if self._used_tics % 2 == 1 else hold(Button.FORWARD)
