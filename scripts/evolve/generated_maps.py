"""Extra held-out maps from OBLIGE: generate, record the recipe, and check each one without a model.

OBLIGE is an external GPL program built outside the repo; its output WADs stay under
~/symbiont-runs/oblige/wads and are never committed. `generate` writes the WADs and a sha256 list;
`check` applies the declared keep rule (static route check, engine load, scripted walker) and writes
the kept list. No model plays any map here.

Usage: generated_maps.py generate|check --oblige-src DIR --wads DIR [--out FILE] [--iwad WAD]
"""

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import smoke_levels  # noqa: E402 - needs the sibling path added above
import verify_routes  # noqa: E402

from symbiont.act1.engine import Wads  # noqa: E402
from symbiont.act1.wad import WadError, read_map  # noqa: E402

COUNT = 90
FIRST_SEED = 7001
SIZES = ("tiny", "small", "regular")
THEMES = ("original", "tech", "urban")
FIXED = {"engine": "zdoom", "game": "doom2", "length": "single"}
MAP_IN_PWAD = "MAP01"
KEEP_LIMIT = 40


def config_for(index: int) -> dict[str, str]:
    """The settings of generated map `index` (0-based): size cycles fastest, then theme."""
    return {**FIXED, "size": SIZES[index % 3], "theme": THEMES[(index // 3) % 3]}


def name_for(index: int) -> str:
    """The map's id: OB0001 and so on."""
    return f"OB{index + 1:04d}"


STRUCTURE_LUMPS = ("THINGS", "LINEDEFS", "VERTEXES", "SECTORS")


def structure_sha256(wad_bytes: bytes) -> str:
    """Hash of the lumps that fix the map's shape and contents; textures vary between runs."""
    count, offset = struct.unpack("<ii", wad_bytes[4:12])
    wanted = hashlib.sha256()
    for entry in range(count):
        position, size, name = struct.unpack("<ii8s", wad_bytes[offset + 16 * entry :][:16])
        if name.rstrip(b"\0").decode() in STRUCTURE_LUMPS:
            wanted.update(wad_bytes[position : position + size])
    return wanted.hexdigest()


def indices(args: argparse.Namespace) -> range:
    """The map indices this run covers; the defaults are the original 90."""
    return range(args.start_index, args.start_index + args.count)


def generate(args: argparse.Namespace) -> None:
    """Write every WAD and the recipe (seed, settings, sha256) as lines of text."""
    sys.path.insert(0, str(args.oblige_src))
    from pyoblige.oblige import DoomLevelGenerator

    args.wads.mkdir(parents=True, exist_ok=True)
    lines = []
    for index in indices(args):
        generator = DoomLevelGenerator(FIRST_SEED + index)
        generator.set_config(config_for(index))
        path = args.wads / f"{name_for(index).lower()}.wad"
        generator.generate(str(path))
        data = path.read_bytes()
        config = config_for(index)
        lines.append(f"{name_for(index)} seed={FIRST_SEED + index} size={config['size']} "
                     f"theme={config['theme']} file_sha256={hashlib.sha256(data).hexdigest()} "
                     f"structure_sha256={structure_sha256(data)}")  # fmt: skip
    (args.wads / "recipe.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:3]), "...", len(lines), "maps")


def check_one(iwad: Path, pwad: Path) -> dict[str, Any]:
    """Static route check, engine load, then the scripted walker; stops at the first failure."""
    try:
        static = smoke_levels.static_route_check(read_map(pwad.read_bytes(), MAP_IN_PWAD))
    except (WadError, OSError, ValueError) as error:
        return {"kept": False, "stage": "read", "reason": type(error).__name__}
    if not static.passed:
        return {"kept": False, "stage": "static", "reason": static.reason.split(":")[0]}
    try:
        walk = verify_routes.verify_level(Wads(iwad, pwad), MAP_IN_PWAD)
    except (WadError, OSError, ValueError, RuntimeError) as error:
        return {"kept": False, "stage": "engine", "reason": type(error).__name__}
    return {
        "kept": walk.reached_exit,
        "stage": "walker",
        "reason": "" if walk.reached_exit else "stopped",
    }


def check(args: argparse.Namespace) -> None:
    """The declared keep rule on every map in seed order; the first KEEP_LIMIT passing are kept."""
    results, kept = {}, []
    for index in indices(args):
        name = name_for(index)
        verdict = check_one(args.iwad, args.wads / f"{name.lower()}.wad")
        results[name] = verdict
        if verdict["kept"] and len(kept) < args.keep_limit:
            kept.append(name)
        print(name, verdict, flush=True)
    stages = {n: "kept" if v["kept"] else v["stage"] for n, v in results.items()}
    passing = sum(v["kept"] for v in results.values())
    document = {"kept": kept, "checked": args.count, "passing": passing, "stages": stages}
    if args.out:
        args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(json.dumps({k: document[k] for k in ("passing", "checked")}), len(kept), "kept")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("generate", "check"))
    parser.add_argument("--oblige-src", type=Path, default=Path.home() / "symbiont-runs/oblige/src")
    parser.add_argument("--wads", type=Path, default=Path.home() / "symbiont-runs/oblige/wads")
    parser.add_argument("--iwad", type=Path, default=Path("data/freedoom/freedoom2.wad"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--count", type=int, default=COUNT)
    parser.add_argument("--keep-limit", type=int, default=KEEP_LIMIT)
    args = parser.parse_args(argv)
    {"generate": generate, "check": check}[args.phase](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
