"""Level smoke test: which Freedoom levels Evolve may use, published before any selection.

Training levels get the static route check and 8 decisions of the scripted explorer; held-out
levels get the static route check and an engine load with zero decisions (plan ruling 3: no
episode on a held-out level before the freeze). A dropped level is listed with its reason in the
local file and with a short label in the published one.

Usage: smoke_levels.py --wad data/freedoom/freedoom2.wad [--project freedoom1]
       --out ~/symbiont-runs/evolve/levels.json --publish results/evolve-levels.json
"""

import argparse
import dataclasses
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

from symbiont.act1.episode import MapKnowledge, RunLog, run_episode  # noqa: E402 - path set above
from symbiont.act1.evolve_split import SmokeResult  # noqa: E402
from symbiont.act1.game_fitness import ALL_KEY_COLORS  # noqa: E402
from symbiont.act1.levels import LevelSplit, Project, level_names, split_of  # noqa: E402
from symbiont.act1.map_index import build_index  # noqa: E402
from symbiont.act1.navmap import NoPath, build_navmap  # noqa: E402
from symbiont.act1.policies import policy_named  # noqa: E402
from symbiont.act1.steplog import MoveRun  # noqa: E402
from symbiont.act1.wad import MapGeometry, WadError, read_map  # noqa: E402

PLAYER_ONE_START = 1  # Doom thing type of the player 1 start
EXPLORER_DECISIONS = 8  # plan T17
PASS = SmokeResult(passed=True, reason="")
SCHEMA = "evolve-levels-v1"
LABEL = "static route check plus scripted explorer on training levels [measured]"

EngineLoader = Callable[[Path, str], Any]


def _drop(reason: str) -> SmokeResult:
    """A level that failed, with the reason."""
    return SmokeResult(passed=False, reason=reason)


def static_route_check(geometry: MapGeometry) -> SmokeResult:
    """Pass when the player 1 start has a walk to an exit, every key held and every door open."""
    starts = [thing for thing in geometry.things if thing.type == PLAYER_ONE_START]
    if not starts:
        return _drop("no_start: the map has no player 1 start")
    nav = build_navmap(geometry, build_index(geometry))
    start = (float(starts[0].x), float(starts[0].y))
    found = nav.nearest(start, nav.features("exit"), ALL_KEY_COLORS, closed=frozenset())
    if isinstance(found, NoPath):
        return _drop(f"no_route: no route to the exit: {found.reason}")
    if found[1].hazards:  # a route that shuts a door behind itself is not a route
        return _drop(f"unsafe_route: {found[1].hazards[0]}")
    return PASS


def default_engine_loader(wad: Path, level: str) -> Any:
    """Seam: the only place this script starts ViZDoom."""
    from symbiont.act1.engine import make_game

    return make_game(wad, level)


def explorer_plays(wad: Path, level: str, loader: EngineLoader) -> SmokeResult:
    """Eight decisions of the scripted explorer: at least one move, no crash."""
    geometry = read_map(wad.read_bytes(), level)
    index = build_index(geometry)
    knowledge = MapKnowledge(index, build_navmap(geometry, index))
    runs: list[MoveRun] = []
    game = loader(wad, level)
    try:
        policy = policy_named("scripted_explorer", 1)
        run_episode(
            game, policy.reply, EXPLORER_DECISIONS, RunLog(on_move=runs.append), knowledge=knowledge
        )
    finally:
        game.close()
    return PASS if runs else _drop("no_move: the explorer played no move")


def engine_loads(wad: Path, level: str, loader: EngineLoader) -> SmokeResult:
    """Start the engine on the level and close it: zero decisions, no episode."""
    loader(wad, level).close()
    return PASS


def smoke_level(wad: Path, level: str, loader: EngineLoader) -> SmokeResult:
    """One level's verdict. A crash drops the level with the exception class as its reason."""
    try:
        static = static_route_check(read_map(wad.read_bytes(), level))
        if not static.passed:
            return static
        if split_of(level) == LevelSplit.HELD_OUT:
            return engine_loads(wad, level, loader)
        return explorer_plays(wad, level, loader)
    except (WadError, OSError, ValueError, RuntimeError) as error:
        return _drop(f"crash: {type(error).__name__}")


def smoke_all(
    wad: Path, project: Project, loader: EngineLoader = default_engine_loader
) -> dict[str, SmokeResult]:
    """Every level of the project's WAD, in play order."""
    return {level: smoke_level(wad, level, loader) for level in level_names(project)}


def label_of(result: SmokeResult) -> str:
    """The short published label: 'pass' or 'drop_<kind>'."""
    return "pass" if result.passed else "drop_" + result.reason.split(":")[0]


def publishable(results: Mapping[str, SmokeResult]) -> dict[str, Any]:
    """Level ids and pass or drop labels only; reasons stay in the local file."""
    labels = {level: label_of(result) for level, result in results.items()}
    dropped = sum(label != "pass" for label in labels.values())
    return {
        "schema": SCHEMA,
        "label": LABEL,
        "levels": labels,
        "counts": {"pass": len(labels) - dropped, "drop": dropped},
    }


def main(argv: list[str] | None = None) -> int:
    """Run the smoke test and write the local and published files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--project", type=Project, choices=list(Project), default=Project.FREEDOOM2)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--publish", type=Path, required=True)
    args = parser.parse_args(argv)
    results = smoke_all(args.wad, args.project)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({k: dataclasses.asdict(v) for k, v in results.items()}, indent=1)
    )
    args.publish.write_text(json.dumps(publishable(results), indent=1) + "\n")
    print(json.dumps(publishable(results)["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
