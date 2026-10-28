"""Build Freedoom decision items by warping the player to seeded points in ViZDoom."""

import logging
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from gate_doom import DoomOracle, oracle_for

from symbiont.act1.engine import KeyTracker, make_game, view_from_engine
from symbiont.act1.env_text import describe, route_hints
from symbiont.act1.map_index import MapIndex, build_index
from symbiont.act1.navmap import NavMap, build_navmap
from symbiont.act1.wad import MapGeometry, read_map

progress = logging.getLogger(__name__)
SETTLE_TICS = 4  # tics after the warp so the engine state reflects the new position
TURN_TICS_MAX = 40  # a random turn of up to this many tics gives a random facing
ATTEMPTS_PER_ITEM = 150


@dataclass(frozen=True)
class DoomItem:
    """One decision: the observation Act 1 would show, and what the oracle accepts."""

    item_id: str
    map_name: str
    observation: str
    oracle: DoomOracle


def _bounds(geometry: MapGeometry) -> tuple[int, int, int, int]:
    xs = [v[0] for v in geometry.vertices]
    ys = [v[1] for v in geometry.vertices]
    return min(xs), max(xs), min(ys), max(ys)


def _warp_and_look(game: Any, rng: random.Random, box: tuple[int, int, int, int]) -> Any | None:
    """Warp to a random point, turn a random amount; None when the episode ended (death, exit)."""
    if game.is_episode_finished():
        game.new_episode()
    x = rng.randint(box[0], box[1])
    y = rng.randint(box[2], box[3])
    game.send_game_command(f"warp {x} {y}")
    game.make_action([0] * 6, SETTLE_TICS)
    game.make_action([0, 0, 1, 0, 0, 0], rng.randint(0, TURN_TICS_MAX))
    return game.get_state()


def _sample_once(
    game: Any, nav: NavMap, index: MapIndex, rng: random.Random, box: tuple[int, int, int, int]
) -> tuple[str, DoomOracle] | None:
    """One warped state described as Act 1 would; None when the route finder has nothing to say."""
    engine_state = _warp_and_look(game, rng, box)
    if engine_state is None:
        return None
    view = view_from_engine(engine_state, KeyTracker(), index)
    view = replace(view, routes=route_hints(nav, view))
    oracle = oracle_for(view)
    return None if oracle is None else (describe(view), oracle)


def build_map_items(
    wad: Path, map_name: str, count: int, seed: int, kind_cap: int
) -> list[DoomItem]:
    """`count` items on one map, at most `kind_cap` per oracle kind; raises if it cannot."""
    geometry = read_map(wad.read_bytes(), map_name)
    index = build_index(geometry)
    nav = build_navmap(geometry, index)
    rng, box = random.Random(seed), _bounds(geometry)
    game = make_game(wad, map_name)
    game.new_episode()
    items: list[DoomItem] = []
    kinds: dict[str, int] = {}
    skipped = 0
    try:
        for _ in range(ATTEMPTS_PER_ITEM * count):
            sampled = _sample_once(game, nav, index, rng, box)
            if sampled is None or kinds.get(sampled[1].kind, 0) >= kind_cap:
                skipped += 1
                continue
            kinds[sampled[1].kind] = kinds.get(sampled[1].kind, 0) + 1
            items.append(DoomItem(f"doom-{map_name}-{len(items) + 1:02d}", map_name, *sampled))
            if len(items) == count:
                progress.info("%s: %d items, %d points skipped", map_name, count, skipped)
                return items
    finally:
        game.close()
    raise RuntimeError(f"{map_name}: only {len(items)} of {count} items in the attempt budget")
