"""Routes over one map's walls and doors: the front door of the nav modules (pure).

A grid rasterized from the walls, not a sector graph, because Doom sectors can be concave and a
straight line between portal midpoints can cut through a wall. navbuild, navgrid, navsearch,
navroute and navdiagnose do the work; this module lists doors, exits and keys and hands out
`Route | NoPath`. A NoPath always names what blocks; a route is never guessed.
"""

from collections.abc import Iterable, Iterator, Sequence

from symbiont.act1.map_index import MapIndex
from symbiont.act1.navbuild import SectorState, sector_box
from symbiont.act1.navdiagnose import explain_unreachable
from symbiont.act1.navgrid import WalkGrid
from symbiont.act1.navmech import build_mechanisms, world_from_heights
from symbiont.act1.navplan import Planned, RoutePlanner, Stage, keys_needed, route_from_plan
from symbiont.act1.navsearch import DoorAwareSearch, DoorRules
from symbiont.act1.navtypes import (
    DOOR_REACH,
    EXIT_REACH,
    KEY_REACH,
    Feature,
    NoPath,
    Route,
    Segment,
    Waypoint,
    WorldNow,
    held_colours,
)
from symbiont.act1.wad import MapGeometry

__all__ = [
    "Feature",
    "NavMap",
    "NoPath",
    "Route",
    "Segment",
    "Waypoint",
    "build_navmap",
    "held_colours",
]


class NavMap:
    """Routes over one map: lists doors, exits and keys, and finds the shortest walk."""

    def __init__(self, geometry: MapGeometry, index: MapIndex) -> None:
        self._geometry = geometry
        self._index = index
        mechanisms = build_mechanisms(geometry)
        self._grid = WalkGrid(geometry, index, mechanisms)
        self._mechanisms = mechanisms
        self._planner = RoutePlanner(geometry, self._grid, mechanisms)

    # --- features ---------------------------------------------------------------------------

    def features(self, kind: str) -> tuple[Feature, ...]:
        """Doors, exits or keys on the map; raises ValueError for any other kind."""
        if kind == "door":
            return tuple(self._door_features())
        if kind == "exit":
            return tuple(self._exit_features())
        if kind == "key":
            return tuple(self._key_features())
        raise ValueError(f"unknown feature kind {kind!r}; known: door, exit, key")

    def _key_features(self) -> Iterator[Feature]:
        for k in self._index.keys:
            label = f"{k.color.title()}{'Card' if k.kind == 'card' else 'Skull'}"
            under = self._grid.sector_at(k.x, k.y)
            yield Feature("key", label, k.x, k.y, KEY_REACH, key_colour=k.color, item_sector=under)

    def _door_features(self) -> Iterator[Feature]:
        """One per door sector; a door whose sector the index could not determine is skipped."""
        seen: set[int] = set()
        for door in self._index.doors:
            sector = door.sector
            if sector is None or sector in seen:
                continue
            box = sector_box(self._geometry, sector)
            if box is None:
                continue
            seen.add(sector)
            (x0, y0), (x1, y1) = box
            yield Feature(
                "door",
                "door",
                (x0 + x1) / 2,
                (y0 + y1) / 2,
                DOOR_REACH,
                door.key_colour,
                sector,
                faces=self._grid.door_faces[sector],
            )

    def _exit_features(self) -> Iterator[Feature]:
        for exit_ in self._index.exits:
            line = self._geometry.linedefs[exit_.line]
            (x1, y1), (x2, y2) = self._geometry.vertices[line.v1], self._geometry.vertices[line.v2]
            yield Feature(
                "exit",
                "exit",
                exit_.mid[0],
                exit_.mid[1],
                EXIT_REACH,
                secret=exit_.secret,
                walk_through=exit_.walkover,
                faces=((x1, y1, x2, y2),),
            )

    def _states_now(self, heights: Sequence[tuple[float, float]]) -> list[SectorState] | None:
        """The engine's sector heights as planner states, None when none were given."""
        if not heights:
            return None
        base = self._grid.base_states
        return world_from_heights(self._geometry, base, self._mechanisms, heights)

    def _why_not(
        self,
        start: int,
        stuck: Stage,
        rules: DoorRules,
        candidates: Sequence[Feature],
    ) -> str:
        """Blame a missing key if holding every key would give a plan, else the last blocker."""
        names = ", ".join(sorted({c.label for c in candidates}))
        unlocked = self._planner.plan(start, candidates, rules.with_every_key())
        if isinstance(unlocked, Planned):
            needed = " and ".join(keys_needed(unlocked, rules.held))
            return f"locked door: needs {needed} key on the way to {names}"
        search = DoorAwareSearch(stuck.grid)
        targets = stuck.grid.target_cells(candidates)
        return explain_unreachable(search, stuck.start, targets, rules, candidates)

    # --- routes -----------------------------------------------------------------------------

    def path(
        self,
        from_xy: tuple[float, float],
        to: Feature | tuple[float, float],
        keys_held: Iterable[str],
        closed: frozenset[int] | None = None,
    ) -> Route | NoPath:
        """Route from a position to a feature or point; NoPath says what blocks, never a guess."""
        target = to if isinstance(to, Feature) else Feature("object", "point", to[0], to[1])
        found = self.nearest(from_xy, [target], keys_held, closed)
        return found if isinstance(found, NoPath) else found[1]

    def nearest(
        self,
        from_xy: tuple[float, float],
        candidates: Sequence[Feature],
        keys_held: Iterable[str],
        closed: frozenset[int] | None = None,
    ) -> tuple[Feature, Route] | NoPath:
        """The candidate with the shortest walking route (not straight-line), with its route.

        `closed` lists the door sectors that are shut right now (None: assume all are). A shut door
        can be entered only from where its use-special can be pressed; an open one from anywhere.
        """
        return self.nearest_now(WorldNow(closed), from_xy, candidates, keys_held)

    def nearest_now(
        self,
        world: WorldNow,
        from_xy: tuple[float, float],
        candidates: Sequence[Feature],
        keys_held: Iterable[str],
    ) -> tuple[Feature, Route] | NoPath:
        """`nearest` over the world as the engine reports it: lifts called, switches pressed."""
        if not candidates:
            return NoPath("nothing of that kind on this map")
        start = self._grid.start_cell(from_xy)
        if start is None:
            return NoPath(
                f"start position {from_xy[0]:.0f},{from_xy[1]:.0f} is not on walkable floor"
            )
        targets = self._grid.target_cells(candidates)
        if not targets:
            names = ", ".join(sorted({c.label for c in candidates}))
            return NoPath(f"{names} is not on walkable floor (no free cell within reach)")
        rules = DoorRules(held_colours(keys_held), world.closed)
        states = self._states_now(world.heights)
        planned = self._planner.plan(start, candidates, rules, states)
        if not isinstance(planned, Planned):
            return NoPath(self._why_not(start, planned, rules, candidates))
        return planned.goal, route_from_plan(planned, planned.goal)


def build_navmap(geometry: MapGeometry, index: MapIndex) -> NavMap:
    """Build the route finder for one parsed map."""
    return NavMap(geometry, index)
