"""Per-arm probe table from episode summaries, replay sidecars and the spend ledger (counts only).

Violation prevented: Paper Tiger in the probe. An arm that "plays" but never exits, or that costs
more than its run cap, must show in the table; so exits, deaths, tagged mistakes, route progress
(the share of the walking distance to the exit covered, so standing still scores zero), kills,
latency percentiles, token counts and ledger cost are printed side by side for every arm. A game
with no ledger rows or no sidecar raises, so a missing game never reads as zero cost or zero kills.

    uv run python scripts/act1/spark_report.py --summaries S.jsonl... --video DIR --run NAME
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from symbiont.act1.episode import load_run_log
from symbiont.act1.map_index import build_index
from symbiont.act1.navmap import NavMap, build_navmap
from symbiont.act1.wad import read_map
from symbiont.egress.spend import Ledger

ALL_KEYS = ("blue", "red", "yellow")  # route length ignores locked doors: progress, not key logic


def route_progress(nav: NavMap, start: tuple[float, float], end: tuple[float, float]) -> float:
    """Share of the walking distance to the exit covered between start and end, clamped to 0..1.

    Raises ValueError when no route to an exit exists from the start.
    """
    exits = nav.features("exit")
    first = nav.nearest(start, list(exits), ALL_KEYS)
    last = nav.nearest(end, list(exits), ALL_KEYS)
    if not isinstance(first, tuple):
        raise ValueError("no route to an exit from the start position")
    if not isinstance(last, tuple):
        return 0.0
    return max(0.0, min(1.0, 1.0 - last[1].length / first[1].length))


def percentile(values: list[float], share: float) -> float:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def game_row(summary: dict[str, Any], video: Path, wad: bytes, episodes: Path) -> dict[str, Any]:
    """One game's numbers; raises FileNotFoundError when its sidecar or decision log is missing."""
    level, policy, seed = summary["level"], summary["policy"], summary["seed"]
    stem = f"{level}-{policy}-s{seed}"
    sidecar = json.loads((video / f"{stem}.json").read_text())
    geometry = read_map(wad, level)
    nav = build_navmap(geometry, build_index(geometry))
    start, end = sidecar["path_ends"]
    log = load_run_log(episodes / level / f"{stem}.decisions.jsonl")
    return {
        "game": stem,
        "label": f"{level}-s{seed}-{policy.removeprefix('spark_')}",
        "ended": summary["ended"],
        "pains": sum(summary["pains"].values()),
        "progress": route_progress(nav, tuple(start), tuple(end)),
        "kills": sidecar["stats"]["kills"],
        "died": bool(sidecar["stats"]["dead"]),
        "seconds": [decision.model_seconds for decision in log],
        "decisions": summary["decisions"],
    }


def ledger_by_game(ledger: Ledger, run: str) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ledger.entries():
        if row["run"] == run:
            rows[row["label"]].append(row)
    return rows


def arm_summary(games: list[dict[str, Any]], calls: list[dict[str, Any]]) -> dict[str, Any]:
    """One arm's table row from its games and its ledger rows; raises ValueError with no calls."""
    if not calls:
        raise ValueError("an arm with no ledger rows cannot be priced")
    seconds = [s for game in games for s in game["seconds"]]
    tokens = {
        name: round(statistics.mean(call[name] for call in calls))
        for name in ("prompt", "cached", "completion", "reasoning")
    }
    return {
        "games": len(games), "exits": sum(g["ended"] == "exited" for g in games),
        "died": sum(g["died"] for g in games), "pains": [g["pains"] for g in games],
        "progress": [round(g["progress"], 2) for g in games], "kills": [g["kills"] for g in games],
        "sec_median": round(statistics.median(seconds), 1),
        "sec_p90": round(percentile(seconds, 0.9), 1),
        "tokens_per_move": tokens,
        "cost_usd": round(sum(c["cost_usd"] for c in calls), 4), "calls": len(calls),
    }  # fmt: skip


def read_summaries(paths: list[str]) -> list[dict[str, Any]]:
    lines = [line for path in paths for line in Path(path).read_text().splitlines() if line]
    return [json.loads(line) for line in lines]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in ("video", "episodes", "run", "wad"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--summaries", nargs="+", required=True)
    args = parser.parse_args(argv)
    summaries = read_summaries(args.summaries)
    wad = Path(args.wad).expanduser().read_bytes()
    video, episodes = Path(args.video).expanduser(), Path(args.episodes).expanduser()
    games = [game_row(summary, video, wad, episodes) for summary in summaries]
    priced = ledger_by_game(Ledger(), args.run)
    table = {}
    for policy in sorted({summary["policy"] for summary in summaries}):
        arm = [g for g, s in zip(games, summaries, strict=True) if s["policy"] == policy]
        calls = [call for game in arm for call in priced[game["label"]]]
        table[policy] = arm_summary(arm, calls)
    print(json.dumps(table, indent=1))


if __name__ == "__main__":
    main()
