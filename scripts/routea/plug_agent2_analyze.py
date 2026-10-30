"""PLUG-AGENT-2 pilot analysis, as frozen: paired per-point differences, sign-flip, BCa, counts.

Per point the share of `forced` branches minus the share of `none` branches that show the outcome
(the same normalized error line; any failure of the point's program). Voided points drop out and
are counted per source. Output holds numbers and ids only. Usage: plug_agent2_analyze.py RECORDS OUT
"""

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import fmean

from plug_agent2_stats import bca_interval, sign_flip_p


def arm_of(branch: dict) -> str:
    """The arm is defined by the note: the branch records carry the source arm (always none) under
    `arm`, so `note_shown` decides."""
    return "forced" if branch["note_shown"] else "none"


def share(branches: list[dict], arm: str, outcome: str) -> float:
    chosen = [b[outcome] for b in branches if arm_of(b) == arm]
    return sum(chosen) / len(chosen)


def paired(records: list[dict], outcome: str) -> list[float]:
    """forced minus none, one number per valid point."""
    return [
        share(r["branches"], "forced", outcome) - share(r["branches"], "none", outcome)
        for r in records
    ]


def outcome_summary(records: list[dict], outcome: str) -> dict:
    diffs = paired(records, outcome)
    low, high = bca_interval(diffs)
    return {
        "none_share": round(fmean(share(r["branches"], "none", outcome) for r in records), 3),
        "forced_share": round(fmean(share(r["branches"], "forced", outcome) for r in records), 3),
        "mean_difference": round(fmean(diffs), 3),
        "bca_low": round(low, 3),
        "bca_high": round(high, 3),
        "sign_flip_p": round(sign_flip_p(diffs), 4),
        "tied_points": sum(d == 0 for d in diffs),
    }


def arm_counts(records: list[dict]) -> dict:
    out: dict = {}
    for arm in ("none", "forced"):
        branches = [b for r in records for b in r["branches"] if arm_of(b) == arm]
        out[arm] = {
            "branches": len(branches),
            "mean_steps_lost": round(fmean(b["steps_lost"] for b in branches), 2),
            "replacement_errors": sum(b["replacement_errors"] for b in branches),
            "exit_status": dict(Counter(b["exit_status"] for b in branches)),
        }
    return out


def main() -> None:
    everything = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
    valid = [r for r in everything if "void" not in r and r["branches"]]
    voids = [r for r in everything if r not in valid]
    summary = {
        "points_in_list": len(everything),
        "valid_points": len(valid),
        "voids_by_source": dict(Counter(r["source"] for r in voids)),
        "void_points": [r["point"] for r in voids],
        "generic_environment_points_in_list": 11,  # the frozen list: all 11 are generic environment
        "same_error_line": outcome_summary(valid, "repeated"),
        "program_fails_any_error": outcome_summary(valid, "same_program_failed"),
        "arms": arm_counts(valid),
    }
    Path(sys.argv[2]).write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
