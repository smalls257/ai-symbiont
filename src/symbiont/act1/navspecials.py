"""What each vanilla linedef special does to a route (pure data).

Source: Chocolate Doom p_spec.c, p_switch.c, p_doors.c, p_floor.c, p_plats.c, p_telept.c; Freedoom
uses the vanilla numbers 1 to 141. A special is modeled, has no effect on walking, or is
UNMODELED with its reason; an unlisted number raises `UnknownSpecialError`, never reads as a wall.
"""

from dataclasses import dataclass
from enum import StrEnum


class UnknownSpecialError(ValueError):
    """A linedef special this table does not list: a route over it would be a guess."""


class Trigger(StrEnum):
    """How a player sets a special off."""

    MANUAL = "manual"  # a door the player opens by pressing USE on its own face
    USE = "use"  # a switch: press USE facing the line
    WALK = "walk"  # cross the line
    SHOOT = "shoot"  # hit the line with a bullet


class Effect(StrEnum):
    """What a special does to the sectors carrying its tag, as far as walking is concerned."""

    OPEN_DOOR = "open_door"  # the ceiling rises and stays: a shut sector becomes a passage
    OPEN_DOOR_TIMED = "open_door_timed"  # opens, waits about 150 tics, shuts again
    LIFT = "lift"  # the floor lowers to the lowest neighbor, waits, and rises again
    LOWER_FLOOR_LOWEST = "lower_floor_lowest"
    LOWER_FLOOR_HIGHEST = "lower_floor_highest"  # to the highest neighboring floor
    RAISE_FLOOR_NEXT = "raise_floor_next"  # to the nearest higher neighboring floor
    RAISE_FLOOR_CEILING = "raise_floor_ceiling"  # to the lowest neighboring ceiling
    RAISE_FLOOR_BY = "raise_floor_by"  # by `amount` units
    TELEPORT = "teleport"  # to the teleport destination thing in the sector with the tag
    EXIT = "exit"
    SECRET_EXIT = "secret_exit"
    CLOSE_DOOR = "close_door"  # the ceiling drops to the floor: a passage is lost
    LOWER_CEILING = "lower_ceiling"  # a ceiling (or a crusher) comes down on the sector
    NO_ROUTE_EFFECT = "no_route_effect"  # changes nothing a walking route depends on
    UNMODELED = "unmodeled"  # changes the world in a way this planner does not follow


@dataclass(frozen=True)
class Special:
    """One linedef special: how it is set off, what it does, its key, and why if unmodeled."""

    trigger: Trigger
    effect: Effect
    key: str | None = None  # key color a switch door demands
    amount: int = 0  # units, for RAISE_FLOOR_BY; extra lowering margin for LOWER_FLOOR_HIGHEST
    note: str = ""


def _group(
    numbers: tuple[int, ...], trigger: Trigger, effect: Effect, amount: int = 0, note: str = ""
) -> dict[int, Special]:
    """Table entries for several special numbers that share one meaning."""
    return {number: Special(trigger, effect, None, amount, note) for number in numbers}


def _keyed_switch_doors() -> dict[int, Special]:
    """Switch doors that need a key, by the key color vanilla gives each number."""
    keyed = {99: "blue", 133: "blue", 134: "red", 135: "red", 136: "yellow", 137: "yellow"}
    return {n: Special(Trigger.USE, Effect.OPEN_DOOR, color) for n, color in keyed.items()}


def _build_table() -> dict[int, Special]:
    """The whole vanilla table, assembled from its groups."""
    use, walk, shoot = Trigger.USE, Trigger.WALK, Trigger.SHOOT
    table: dict[int, Special] = {}
    # manual doors are opened by their own face; map_index lists them with their key colors
    table.update(
        _group((1, 26, 27, 28, 31, 32, 33, 34, 117, 118), Trigger.MANUAL, Effect.OPEN_DOOR)
    )
    table.update(_group((2, 106, 109, 86, 40), walk, Effect.OPEN_DOOR))
    table.update(_group((61, 103, 112, 115), use, Effect.OPEN_DOOR))
    table.update(_group((4, 90, 105, 108), walk, Effect.OPEN_DOOR_TIMED))
    table.update(_group((29, 63, 111, 114), use, Effect.OPEN_DOOR_TIMED))
    table.update(_group((46,), shoot, Effect.OPEN_DOOR))
    table.update(_keyed_switch_doors())
    table.update(_group((10, 88, 120, 121), walk, Effect.LIFT))
    table.update(_group((21, 62, 122, 123), use, Effect.LIFT))
    table.update(_group((37, 38, 82, 84), walk, Effect.LOWER_FLOOR_LOWEST))
    table.update(_group((23, 60), use, Effect.LOWER_FLOOR_LOWEST))
    table.update(_group((19, 83), walk, Effect.LOWER_FLOOR_HIGHEST))
    table.update(_group((45, 102), use, Effect.LOWER_FLOOR_HIGHEST))
    table.update(_group((36, 98), walk, Effect.LOWER_FLOOR_HIGHEST, 8))
    table.update(_group((70, 71), use, Effect.LOWER_FLOOR_HIGHEST, 8))
    table.update(_group((22, 95, 119, 128, 129, 130), walk, Effect.RAISE_FLOOR_NEXT))
    table.update(_group((18, 20, 68, 69, 131, 132), use, Effect.RAISE_FLOOR_NEXT))
    table.update(_group((47,), shoot, Effect.RAISE_FLOOR_NEXT))
    table.update(_group((5, 56, 91, 94), walk, Effect.RAISE_FLOOR_CEILING))
    table.update(_group((64, 65, 101, 55), use, Effect.RAISE_FLOOR_CEILING))
    table.update(_group((24,), shoot, Effect.RAISE_FLOOR_CEILING))
    table.update(_group((58, 59, 92, 93), walk, Effect.RAISE_FLOOR_BY, 24))
    table.update(_group((15, 66), use, Effect.RAISE_FLOOR_BY, 24))
    table.update(_group((14, 67), use, Effect.RAISE_FLOOR_BY, 32))
    table.update(_group((140,), use, Effect.RAISE_FLOOR_BY, 512))
    table.update(_group((39, 97), walk, Effect.TELEPORT))
    table.update(_group((11,), use, Effect.EXIT))
    table.update(_group((52,), walk, Effect.EXIT))
    table.update(_group((51,), use, Effect.SECRET_EXIT))
    table.update(_group((124,), walk, Effect.SECRET_EXIT))
    table.update(_no_route_effect())
    table.update(_unmodeled())
    return table


def _no_route_effect() -> dict[int, Special]:
    """Specials that close, lower or change lights; closers are audited, not pressed."""
    use, walk = Trigger.USE, Trigger.WALK
    none = Effect.NO_ROUTE_EFFECT
    table: dict[int, Special] = {}
    table.update(_group((3, 16, 75, 76, 107, 110), walk, Effect.CLOSE_DOOR))
    table.update(_group((42, 50, 113, 116), use, Effect.CLOSE_DOOR))
    table.update(_group((41, 43, 49), use, Effect.LOWER_CEILING))
    table.update(_group((44, 72, 6, 25, 73, 77, 141), walk, Effect.LOWER_CEILING))
    table.update(_group((57, 74, 54, 89), walk, none, note="stops a crusher or lift"))
    table.update(_group((12, 13, 17, 35, 79, 80, 81, 104), walk, none, note="changes lights"))
    table.update(_group((138, 139), use, none, note="changes lights"))
    table.update(_group((48,), Trigger.MANUAL, none, note="scrolling wall texture"))
    table.update(_group((85,), Trigger.MANUAL, none, note="scrolling wall texture"))
    table.update(_group((78,), use, none, note="changes a texture"))
    table.update(_group((125, 126), walk, none, note="teleports monsters only"))
    return table


def _unmodeled() -> dict[int, Special]:
    """Specials whose effect the planner does not follow, each with its reason."""
    use, walk, un = Trigger.USE, Trigger.WALK, Effect.UNMODELED
    table: dict[int, Special] = {}
    table.update(_group((7, 127), use, un, note="builds stairs"))
    table.update(_group((8, 100), walk, un, note="builds stairs"))
    table.update(_group((9,), use, un, note="donut"))
    table.update(_group((30, 96), walk, un, note="raises a floor by a texture height"))
    table.update(_group((53, 87), walk, un, note="perpetual lift"))
    return table


SPECIALS: dict[int, Special] = _build_table()


def special_named(number: int) -> Special:
    """The table entry for a nonzero linedef special; raises UnknownSpecialError when unlisted."""
    try:
        return SPECIALS[number]
    except KeyError:
        raise UnknownSpecialError(
            f"linedef special {number} is not in the vanilla table; "
            "add it to navspecials.SPECIALS before routing over this map"
        ) from None
