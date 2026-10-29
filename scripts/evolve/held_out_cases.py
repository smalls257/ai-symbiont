"""The held-out test's arms, maps, cases and level loader, in one place.

The prereg, the runner and the scorer all read the arms, the seeds and the map lists from here, so
none of them can drift from the others after the freeze. The loader resolves a level name to its WAD
files: a Freedoom map from its game's IWAD, a generated map (OBxxxx) from its PWAD on top of
freedoom2.wad, checked against the sha256 declared before any play.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import script_paths

script_paths.add_script_dirs()

import frozen_cards  # noqa: E402 - needs the sibling path added above
import lesson_players  # noqa: E402
import paired_traces  # noqa: E402
from play_case import Loaded  # noqa: E402

from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.engine import Start, Wads, make_game  # noqa: E402
from symbiont.act1.episode import MapKnowledge  # noqa: E402
from symbiont.act1.game_fitness import Case  # noqa: E402
from symbiont.act1.levels import project_of  # noqa: E402
from symbiont.act1.map_index import build_index  # noqa: E402
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting  # noqa: E402
from symbiont.act1.navmap import build_navmap  # noqa: E402
from symbiont.act1.rooms import RoomFinder  # noqa: E402
from symbiont.act1.wad import read_map  # noqa: E402

DECISIONS = 32  # the depth check showed headroom opens between 16 and 32 and stops by 48
CUTOFF = 0.818  # ranker score at which a situational lesson would fire: about 1 decision in 5
MAP_IN_PWAD = "MAP01"
GENERATED_SEEDS = tuple(range(4001, 4010))  # 9 seeds on each of the 40 kept generated maps
FREEDOOM_SEEDS = tuple(range(4001, 4006))  # 5 seeds on each of the 13 Freedoom held-out maps
FREEDOOM_MAPS = (
    *frozen_cards.HELD_OUT_MAPS,
    "E1M4", "E2M3", "E2M7", "E3M6", "E4M1", "E4M5",
)  # fmt: skip
RECIPE_LINE = re.compile(r"^(OB\d{4}) seed=\d+ .*file_sha256=([0-9a-f]{64})", re.MULTILINE)


class Arm(StrEnum):
    """The three conditions, each played on every case."""

    NONE = "none"
    ONE_MOVE = "one_move"
    LESSONS = "lessons"


class MapSet(StrEnum):
    """Which maps a case is on: the generated set decides the headline, Freedoom is apart."""

    GENERATED = "generated"
    FREEDOOM = "freedoom"


@dataclass(frozen=True)
class ArmSetting:
    """The card in front of the prompt, and whether a would-fire lesson is shown."""

    card: Card
    delivery: lesson_players.Delivery


ARM_SETTINGS = {
    Arm.NONE: ArmSetting(frozen_cards.NO_CARD, lesson_players.Delivery.NOTHING),
    Arm.ONE_MOVE: ArmSetting(paired_traces.ONE_MOVE, lesson_players.Delivery.NOTHING),
    Arm.LESSONS: ArmSetting(frozen_cards.NO_CARD, lesson_players.Delivery.ADVICE),
}


class WrongMapCountError(ValueError):
    """The kept-map list does not hold the 40 maps the prereg names."""


class MapFileMismatchError(RuntimeError):
    """A generated map's file differs from the sha256 declared before any play."""


def generated_maps(kept_file: Path) -> tuple[str, ...]:
    """The 40 kept generated maps, from the committed keep-rule result."""
    kept = tuple(json.loads(kept_file.read_text())["kept"])
    if len(kept) != 40:
        raise WrongMapCountError(f"{kept_file} keeps {len(kept)} maps, the prereg names 40")
    return kept


def cases_on(maps: tuple[str, ...], seeds: tuple[int, ...]) -> tuple[Case, ...]:
    """Every map with every seed; normal skill, no cut moves, one case per (map, seed)."""
    return tuple(
        Case(level, seed, NORMAL_SKILL, CutSetting.NONE) for seed in seeds for level in maps
    )


def all_cases(kept_file: Path) -> tuple[Case, ...]:
    """Generated cases first (the headline set), then the Freedoom cases."""
    return cases_on(generated_maps(kept_file), GENERATED_SEEDS) + cases_on(
        FREEDOOM_MAPS, FREEDOOM_SEEDS
    )


def all_levels(kept_file: Path) -> frozenset[str]:
    """Every map name a case may use; the engine player refuses any other."""
    return frozenset(case.level for case in all_cases(kept_file))


def map_set_of(level: str) -> MapSet:
    """GENERATED for an OBxxxx id, else FREEDOOM."""
    return MapSet.GENERATED if level.startswith("OB") else MapSet.FREEDOOM


def declared_hashes(declaration: Path) -> dict[str, str]:
    """Map id to the file sha256 in the generated-maps declaration."""
    return dict(RECIPE_LINE.findall(declaration.read_text()))


def require_declared_files(maps: tuple[str, ...], wads: Path, declaration: Path) -> None:
    """Every generated map file equals its declared sha256; a changed or missing file is refused."""
    declared = declared_hashes(declaration)
    for name in maps:
        found = hashlib.sha256((wads / f"{name.lower()}.wad").read_bytes()).hexdigest()
        if declared.get(name) != found:
            raise MapFileMismatchError(f"{name}: the file is not the one declared")


@dataclass(frozen=True)
class LevelLoader:
    """Picklable loader for EngineSetup: `wad` is the Freedoom data directory."""

    wads: Path

    def __call__(self, freedoom: Path, case: Case) -> Loaded:
        """The game, its map knowledge and its room finder for one case."""
        source, name = self.files(freedoom, case.level)
        data = (source.pwad if isinstance(source, Wads) else source).read_bytes()
        geometry = read_map(data, name)
        index = build_index(geometry)
        knowledge = MapKnowledge(index, build_navmap(geometry, index))
        game = make_game(source, name, Start(case.seed, case.skill))
        return game, knowledge, RoomFinder(geometry)

    def files(self, freedoom: Path, level: str) -> tuple[Path | Wads, str]:
        """The IWAD (or IWAD plus PWAD) and the map's name inside it."""
        if map_set_of(level) == MapSet.GENERATED:
            return Wads(freedoom / "freedoom2.wad", self.wads / f"{level.lower()}.wad"), MAP_IN_PWAD
        return freedoom / f"{project_of(level).value}.wad", level
