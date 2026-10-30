"""ViZDoom adapter: raw engine state to the plain `GameStateView` the model is shown (periphery).

Violation prevented: Silent Fallback. A sector convention that differs from the WAD, or a key that
vanishes away from the player, raises instead of reporting a wrong door or inventory state.
"""

import math
from pathlib import Path
from typing import Any

from symbiont.act1.env_text import (
    KEY_NAMES,
    GameStateView,
    SeenObject,
    Viewpoint,
    doors_in_reach,
    layout_from_depth,
    locate_features,
    normalize_degrees,
)
from symbiont.act1.map_index import MapIndex, closed_sector_ids
from symbiont.act1.moves import Button

DOOR_RANGE_UNITS = 600.0
IGNORED_OBJECTS = frozenset({"DoomPlayer", "BulletPuff", "Blood", "TeleportFog"})
PICKUP_RANGE_UNITS = 64.0
DOOR_REACH_UNITS = 96.0  # door-line distance at which a USE press can still reach the door


# --- ViZDoom adapter: raw engine state -> plain GameStateView -------------------------------------


def make_game(wad: Path, map_name: str = "MAP01", seed: int = 1) -> Any:
    """A synchronous, windowless ViZDoom game on the given WAD map."""
    import vizdoom as vzd

    game = vzd.DoomGame()
    game.set_doom_game_path(str(wad))
    game.set_doom_map(map_name)
    game.set_seed(seed)
    game.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    game.set_labels_buffer_enabled(True)
    game.set_depth_buffer_enabled(True)
    game.set_objects_info_enabled(True)
    game.set_sectors_info_enabled(True)
    game.set_available_buttons(
        [
            vzd.Button.MOVE_FORWARD,
            vzd.Button.MOVE_BACKWARD,
            vzd.Button.TURN_LEFT,
            vzd.Button.TURN_RIGHT,
            vzd.Button.ATTACK,
            vzd.Button.USE,
        ]
    )
    game.set_available_game_variables(
        [
            vzd.GameVariable.HEALTH,
            vzd.GameVariable.SELECTED_WEAPON_AMMO,
            vzd.GameVariable.POSITION_X,
            vzd.GameVariable.POSITION_Y,
            vzd.GameVariable.ANGLE,
        ]
    )
    game.set_episode_timeout(20000)
    game.set_window_visible(False)
    game.set_mode(vzd.Mode.PLAYER)  # synchronous: the game waits for us
    game.init()
    return game


BUTTON_ORDER = (
    Button.FORWARD,
    Button.BACKWARD,
    Button.TURN_LEFT,
    Button.TURN_RIGHT,
    Button.ATTACK,
    Button.USE,
)


def button_vector(buttons: frozenset[Button]) -> list[int]:
    """Button set to the engine's action vector, in BUTTON_ORDER."""
    return [int(b in buttons) for b in BUTTON_ORDER]


class SectorConventionError(RuntimeError):
    """The engine's sector heights do not match the WAD: door state cannot be trusted."""


def check_sector_convention(wad_sectors: Any, engine_sectors: Any) -> None:
    """ViZDoom 1.2 reports floor_height as the negated WAD floor and ceiling_height as authored.

    Verified against freedoom2.wad MAP01; checked at the start of every episode so a different
    binding version or map fails loudly instead of misreporting which doors are shut.
    """
    if len(wad_sectors) != len(engine_sectors):
        raise SectorConventionError(
            f"sector count differs: WAD {len(wad_sectors)}, engine {len(engine_sectors)}"
        )
    for number, (wad, engine) in enumerate(zip(wad_sectors, engine_sectors, strict=True)):
        if engine.floor_height != -wad.floor or engine.ceiling_height != wad.ceiling:
            raise SectorConventionError(
                f"sector {number}: WAD floor/ceiling {wad.floor}/{wad.ceiling}, "
                f"engine {engine.floor_height}/{engine.ceiling_height}"
            )


class KeyTrackingError(RuntimeError):
    """A key disappeared somewhere the player could not have picked it up."""


class KeyTracker:
    """ViZDoom exposes no inventory, so a key counts as held once it vanishes within pickup range.

    Any other disappearance raises: guessing "not held" would silently tell the model it has no key.
    """

    def __init__(self) -> None:
        self._world: dict[int, tuple[str, float, float]] = {}
        self._held: list[str] = []

    def update(self, engine_state: Any) -> tuple[str, ...]:
        """Note keys that vanished within pickup range; raise on any other vanish."""
        x, y = engine_state.game_variables[2], engine_state.game_variables[3]
        now = {
            o.id: (o.name, o.position_x, o.position_y)
            for o in engine_state.objects
            if o.name in KEY_NAMES
        }
        for key_id, (name, kx, ky) in self._world.items():
            if key_id in now:
                continue
            gap = math.hypot(kx - x, ky - y)
            if gap > PICKUP_RANGE_UNITS:
                raise KeyTrackingError(f"{name} vanished {gap:.0f} units from the player")
            self._held.append(name)
        self._world = now
        return tuple(self._held)


def view_from_engine(engine_state: Any, keys: KeyTracker, index: MapIndex) -> GameStateView:
    """Turn the raw engine state into the plain view that `describe` renders."""
    health, ammo, x, y, angle = engine_state.game_variables
    visible_ids = {label.object_id for label in engine_state.labels}
    objects = []
    for obj in engine_state.objects:
        if obj.id not in visible_ids or obj.name in IGNORED_OBJECTS:
            continue
        dx, dy = obj.position_x - x, obj.position_y - y
        bearing = normalize_degrees(math.degrees(math.atan2(dy, dx)) - angle)
        objects.append(SeenObject(obj.name, math.hypot(dx, dy), bearing))
    closed = closed_sector_ids((-s.floor_height, s.ceiling_height) for s in engine_state.sectors)
    doors, exits = locate_features(
        index, closed, Viewpoint((x, y), angle), engine_state.depth_buffer, DOOR_RANGE_UNITS
    )
    return GameStateView(
        health=health,
        ammo=ammo,
        position=(x, y),
        angle_deg=angle,
        objects=tuple(objects),
        doors=doors,
        keys_held=keys.update(engine_state),
        layout=layout_from_depth(engine_state.depth_buffer),
        exits=exits,
        reach_doors=doors_in_reach(index, closed, (x, y), DOOR_REACH_UNITS),
        closed_sectors=closed,
    )
