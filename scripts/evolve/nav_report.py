"""Level navigation report: per Freedoom level, what blocks its route and whether it was walked.

Joins the static route check (smoke_levels.static_route_check) with the lines `verify_routes.py`
wrote. Published: level ids and short labels only. Held-out levels are never played for it
(plan ruling 3), so their engine column reads "not_played".

Usage: nav_report.py --wad data/freedoom/freedoom2.wad --walks DIR_OF_JSONL --publish FILE.json
"""

import argparse
import json
import sys
from pathlib import Path

import script_paths

script_paths.add_script_dirs()

from smoke_levels import static_route_check  # noqa: E402 - path set above

from symbiont.act1.levels import LevelSplit, levels_in, split_of  # noqa: E402
from symbiont.act1.navmech import unmodeled_notes  # noqa: E402
from symbiont.act1.wad import read_map  # noqa: E402

SCHEMA = "evolve-routes-v1"
LABEL = "static route check, then a scripted walker in the engine on training levels [measured]"
# reason text -> blocker kind, first match wins; the texts are navdiagnose's own
BLOCKER_KINDS = (
    ("nothing of that kind", "no_exit_on_map"),
    ("not on walkable floor", "exit_off_floor"),
    ("locked door", "locked_door"),
    ("climb", "climb"),
    ("headroom", "headroom"),
    ("edge of the map", "void"),
    ("a wall", "wall"),
)
WALK_KINDS = (
    ("stuck at", "stuck"),
    ("no path", "no_path"),
    ("tic budget", "tic_budget"),
    ("did not end", "level_not_ended"),
)


def blocker_kind(reason: str) -> str:
    """A short kind for a no-route reason; 'other' when the text matches none."""
    for fragment, kind in BLOCKER_KINDS:
        if fragment in reason:
            return kind
    return "other"


def walk_kind(last_outcome: str) -> str:
    """A short kind for how a walk ended; 'other' when the text matches none."""
    for fragment, kind in WALK_KINDS:
        if fragment in last_outcome:
            return kind
    return "other"


def read_walks(directory: Path) -> dict[str, dict]:
    """The last verify_routes line per level found in the directory's *.jsonl files."""
    walks: dict[str, dict] = {}
    for path in sorted(directory.glob("MAP*.jsonl")):
        for line in path.read_text().splitlines():
            entry = json.loads(line)
            walks[entry["level"]] = entry
    return walks


def level_row(wad: bytes, level: str, walks: dict[str, dict]) -> dict[str, object]:
    """One level's static verdict, blocker kind, unmodeled specials and engine walk."""
    geometry = read_map(wad, level)
    verdict = static_route_check(geometry)
    row: dict[str, object] = {"split": split_of(level).value}
    row["static"] = "pass" if verdict.passed else blocker_kind(verdict.reason)
    row["unmodeled"] = sorted(unmodeled_notes(geometry))
    walk = walks.get(level)
    if split_of(level) == LevelSplit.HELD_OUT or walk is None:
        row["walk"] = "not_played"
    elif walk["reached_exit"]:
        row["walk"] = "exit_reached"
    else:
        row["walk"] = walk_kind(walk["last_outcomes"][-1] if walk["last_outcomes"] else "")
    return row


def build_report(wad: bytes, walks: dict[str, dict]) -> dict[str, object]:
    """The published document: per-level rows and the counts the report quotes."""
    levels = {
        level: level_row(wad, level, walks)
        for level in sorted(levels_in(LevelSplit.TRAINING) + levels_in(LevelSplit.HELD_OUT))
    }
    counts: dict[str, int] = {}
    for row in levels.values():
        split, static, walk = row["split"], row["static"], row["walk"]
        for key in (f"{split}_static_{'pass' if static == 'pass' else 'drop'}", f"{split}_{walk}"):
            counts[key] = counts.get(key, 0) + 1
        if static != "pass":
            counts[f"blocker_{static}"] = counts.get(f"blocker_{static}", 0) + 1
    return {"schema": SCHEMA, "label": LABEL, "levels": levels, "counts": counts}


def main(argv: list[str] | None = None) -> int:
    """Write the report to --publish."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--walks", type=Path, required=True)
    parser.add_argument("--publish", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(args.wad.read_bytes(), read_walks(args.walks))
    args.publish.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
