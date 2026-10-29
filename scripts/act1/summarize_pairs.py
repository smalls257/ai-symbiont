"""Paired plain-versus-personal table from collect_episodes.py's summary lines.

Prevents Silent Fallback in the result: an unpaired (level, seed), a duplicate arm or a summary
line without a pains field stops with the key named, so a missing episode never reads as zero
pain points. Prints counts only (pains by kind, decisions, exit, tokens), no text.

Usage: uv run python scripts/act1/summarize_pairs.py SUMMARY.jsonl [SUMMARY.jsonl ...]
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PLAIN = "glimmer_plain"
PERSONAL = "glimmer_personal"
EXITED = "exited"


def episode_row(summary: dict[str, Any]) -> dict[str, Any]:
    """The reported numbers of one episode; raises KeyError when a field is missing."""
    pains = summary["pains"]
    return {
        "pain_total": sum(pains.values()),
        "pains": pains,
        "decisions": summary["decisions"],
        "exited": summary["ended"] == EXITED,
        "tokens": (summary["tokens_in"] or 0) + (summary["tokens_out"] or 0),
    }


def pair_rows(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (level, seed) with both arms; raises ValueError for a duplicate or lone arm."""
    arms: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for summary in summaries:
        key = (summary["level"], summary["seed"])
        if summary["policy"] in arms[key]:
            raise ValueError(f"{key}: {summary['policy']} appears twice")
        arms[key][summary["policy"]] = episode_row(summary)
    rows = []
    for (level, seed), pair in sorted(arms.items()):
        if set(pair) != {PLAIN, PERSONAL}:
            raise ValueError(f"{(level, seed)}: needs both arms, found {sorted(pair)}")
        rows.append(
            {"level": level, "seed": seed, "plain": pair[PLAIN], "personal": pair[PERSONAL]}
        )
    return rows


def read_summaries(paths: list[Path]) -> list[dict[str, Any]]:
    """Summary lines only: collect_episodes.py also prints one prereg line per scored run."""
    lines = (line for path in paths for line in path.read_text().splitlines() if line.strip())
    return [row for row in map(json.loads, lines) if "policy" in row]


def main(argv: list[str]) -> None:
    rows = pair_rows(read_summaries([Path(arg) for arg in argv]))
    print(json.dumps(rows, indent=1))
    diffs = [row["personal"]["pain_total"] - row["plain"]["pain_total"] for row in rows]
    print(json.dumps({"pairs": len(rows), "paired_pain_differences": diffs}))


if __name__ == "__main__":
    main(sys.argv[1:])
