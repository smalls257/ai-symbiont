"""Build the 30 fixed items once and keep them in the local work directory."""

import json
from pathlib import Path
from typing import Any

from gate_coding import GoldStep, find_gold_step
from gate_doom_items import build_map_items

ITEM_SEED = 20261030
DOOM_PLAN = (("MAP01", 11, 11), ("MAP02", 9, 7))  # map, items, max items of one oracle kind
CODING_TRAJECTORIES = (  # solved Glimmer runs on sqlglot, copied read-only into workdir/traj
    "sqlglot-1309--screen-run1", "sqlglot-1367--screen-run1", "sqlglot-1379--screen-run1",
    "sqlglot-1782--screen-run1", "sqlglot-1782--confirm-run2", "sqlglot-1944--screen-run1",
    "sqlglot-2095--screen-run1", "sqlglot-2443--screen-run1", "sqlglot-2529--screen-run1",
    "sqlglot-2658--screen-run1",
)  # fmt: skip
ITEMS_FILE = "items.json"


def trajectory(workdir: Path, name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((workdir / "traj" / f"{name}.json").read_text())
    return loaded


def doom_items(workdir: Path) -> list[dict[str, Any]]:
    wad = workdir.parent / "freedoom" / "freedoom2.wad"
    found = []
    for map_name, count, kind_cap in DOOM_PLAN:
        for item in build_map_items(wad, map_name, count, ITEM_SEED, kind_cap):
            oracle = item.oracle
            found.append(
                {
                    "item_id": item.item_id,
                    "domain": "freedoom",
                    "observation": item.observation,
                    "oracle_kind": oracle.kind,
                    "go_to_targets": sorted(oracle.go_to_targets),
                    "walk_to_targets": sorted(oracle.walk_to_targets),
                }
            )
    return found


def coding_item(workdir: Path, name: str) -> dict[str, Any]:
    traj = trajectory(workdir, name)
    gold: GoldStep = find_gold_step(traj["messages"], traj["info"]["submission"])
    return {
        "item_id": f"code-{name}",
        "domain": "coding",
        "trajectory": name,
        "gold_index": gold.message_index,
        "gold_path": gold.path,
        "gold_functions": sorted(gold.functions),
    }


def load_or_build_items(workdir: Path) -> list[dict[str, Any]]:
    """The item list; built on first use and then frozen on disk so every arm sees the same one."""
    path = workdir / ITEMS_FILE
    if path.exists():
        loaded: list[dict[str, Any]] = json.loads(path.read_text())
        return loaded
    items = doom_items(workdir) + [coding_item(workdir, name) for name in CODING_TRAJECTORIES]
    path.write_text(json.dumps(items, indent=1))
    return items
