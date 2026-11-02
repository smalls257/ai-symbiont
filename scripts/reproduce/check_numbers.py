"""Tier 2 of REPRODUCE.md: recompute the headline claims from committed files.

Each claim in CLAIMS-style tables below is printed beside the value recomputed from
`results/*.json` and `prereg/`. PASS means recomputed and equal; STORED means the file matches the
claim but holds no data to recompute from; MISMATCH means they disagree. Exit 1 on any MISMATCH.
"""

import hashlib
import json
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
from exact_bounds import bootstrap_mean_interval, clopper_pearson_upper

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "routea"))

# The study's own statistic code, so the bootstrap here is the one that produced the claim.
from plug_r4_primary_stats import RepoTable, bootstrap, coverage  # noqa: E402

EVOLVE_SEED = 20261031  # prereg/2026-11-01-evolve-final-card-confirm.md and ...-replication.md
CORE_V3_SEED = 20261101  # prereg/2026-10-31-core-v3.md
WRONG_BAR = 0.05  # the preregs' bar for the exact upper bound of the wrong-pick rate
MIN_GAIN = 0.05  # the code-fix prereg's smallest gain that counts as better
ROUND_TO_THREE = 0.0005


class Status(StrEnum):
    """What a line of the report means."""

    PASS = "PASS"  # recomputed from committed data and equal to the claim
    STORED = "STORED"  # the file holds the number and it equals the claim; not recomputable
    MISMATCH = "MISMATCH"  # the claim and the committed files disagree


@dataclass(frozen=True)
class Line:
    """One claim beside its recomputed value."""

    claim: str
    claimed: str
    found: str
    status: Status
    note: str = ""


def load(name: str) -> dict:
    """A committed results file; raises FileNotFoundError naming it."""
    return json.loads((ROOT / "results" / name).read_text())


def agrees(found: float, claimed: float, tolerance: float = ROUND_TO_THREE) -> bool:
    """Whether `found` rounds to `claimed` at the claim's printed precision."""
    return abs(found - claimed) <= tolerance


def recomputed(claim: str, claimed: float, found: float, shown: str) -> Line:
    """A line whose `found` value was recomputed here."""
    status = Status.PASS if agrees(found, claimed) else Status.MISMATCH
    return Line(claim, f"{claimed:g}", shown, status)


def stored(claim: str, claimed: float, found: float, why: str) -> Line:
    """A line whose `found` value was read from a file that cannot be recomputed."""
    status = Status.STORED if agrees(found, claimed) else Status.MISMATCH
    return Line(claim, f"{claimed:g}", f"{found:.4f}", status, why)


def file_only(claim: str, found: float, why: str) -> Line:
    """A number the docs do not quote but the files hold; shown so nothing is hidden."""
    return Line(claim, "-", f"{found:.4f}", Status.STORED, why)


def verdict(claim: str, claimed: str, found: str) -> Line:
    """A line comparing the verdict word the rule gives with the claimed one."""
    status = Status.PASS if claimed == found else Status.MISMATCH
    return Line(claim, claimed, found, status)


def wrong_count(rate: float, items: int) -> int:
    """The count of wrong picks behind a stored rate; raises when the rate is not a whole count."""
    count = round(rate * items)
    if abs(count / items - rate) > 0.5 / items:
        raise ValueError(f"{rate} of {items} is not a whole number of items")
    return count


@dataclass(frozen=True)
class ClusterSummary:
    """What the study's code computes from per-cluster counts: coverage, interval, wrong picks."""

    coverage_arm: float
    coverage_reference: float
    gain_interval: tuple[float, float]
    items: int
    wrong: int
    answered: int


def cluster_table(counts: dict[str, list[int]]) -> RepoTable:
    """A RepoTable from {cluster: [positives, right, items, wrong, answered]}."""
    names = sorted(counts)
    grid = np.array([counts[name] for name in names], dtype=float).T
    return RepoTable(tuple(names), *grid)


def summarize_clusters(study: str, arm: str, reference: str) -> ClusterSummary:
    """Rerun the study's coverage and clustered bootstrap on the committed counts."""
    arms = load("repro-cluster-tables.json")[study]["arms"]
    table, base = cluster_table(arms[arm]), cluster_table(arms[reference])
    boot = bootstrap(table, base)
    return ClusterSummary(
        coverage(table),
        coverage(base),
        (boot["gain_low"], boot["gain_high"]),
        int(table.items.sum()),
        int(table.wrong.sum()),
        int(table.answered.sum()),
    )


def interval_lines(
    name: str, found: ClusterSummary, claimed: tuple[float, float, float, float]
) -> list[Line]:
    """Coverage of both arms and both ends of the gain interval, recomputed from the counts."""
    arm, reference, low, high = claimed
    return [
        recomputed(f"{name} coverage, arm", arm, found.coverage_arm, f"{found.coverage_arm:.4f}"),
        recomputed(
            f"{name} coverage, reference",
            reference,
            found.coverage_reference,
            f"{found.coverage_reference:.4f}",
        ),
        recomputed(
            f"{name} gain interval, low end",
            low,
            found.gain_interval[0],
            f"{found.gain_interval[0]:.4f}",
        ),
        recomputed(
            f"{name} gain interval, high end",
            high,
            found.gain_interval[1],
            f"{found.gain_interval[1]:.4f}",
        ),
    ]


def cross_check(claim: str, file_value: float, found: float) -> Line:
    """The stored summary file and the recomputed number must round to the same value."""
    return recomputed(claim, round(file_value, 4), found, f"{found:.4f}")


def plug_round_four() -> list[Line]:
    """Plug round 4, primary: the agree rule against the judge alone on 501 items."""
    primary, bounds = load("plug-r4-scored-primary.json"), load("plug-r4-bounds.json")
    found = summarize_clusters("plug-r4-primary", "agree_rule", "judge_alone")
    wrong = wrong_count(primary["rule"]["wrong_pick"], primary["items"])
    exact = clopper_pearson_upper(found.wrong, found.items)
    gain = found.coverage_arm - found.coverage_reference
    better = found.gain_interval[0] > 0 and gain >= MIN_GAIN and exact < WRONG_BAR
    stored_bound = bounds["arms"]["plug-r4-scored-primary"]["arm"]["exact_upper"]
    return [
        recomputed(
            "Plug r4 agree rule wrong picks (of 501)",
            0,
            found.wrong,
            f"{found.wrong} of {found.items}",
        ),
        recomputed("Plug r4 agree rule exact upper bound", 0.0073, exact, f"{exact:.4f}"),
        cross_check("Plug r4 results file, wrong picks", wrong, found.wrong),
        cross_check("Plug r4 bounds file, exact bound", stored_bound, exact),
        *interval_lines("Plug r4", found, (0.256, 0.128, 0.033, 0.230)),
        recomputed("Plug r4 coverage gain", 0.129, gain, f"{gain:.4f}"),
        verdict(
            "Plug r4 reading (interval above 0, gain >= 0.05, bound < 5%)",
            "better",
            "better" if better else "not better",
        ),
    ]


def code_fix_study() -> list[Line]:
    """The code-fix lessons study on SWE-smith: nightly arm against the agree rule."""
    nightly = load("plug-r4-smith-decision.json")["nightly_vs_agree"]
    found = summarize_clusters("code-fix", "nightly", "agree_rule")
    exact = clopper_pearson_upper(found.wrong, found.items)
    precision = (found.answered - found.wrong) / found.answered
    gain = found.coverage_arm - found.coverage_reference
    better = found.gain_interval[0] > 0 and gain >= MIN_GAIN and exact < WRONG_BAR
    return [
        *interval_lines("Code-fix", found, (0.611, 0.000, 0.556, 0.666)),
        recomputed("Code-fix coverage gain", 0.611, gain, f"{gain:.4f}"),
        recomputed(
            "Code-fix wrong picks (of 924)", 5, found.wrong, f"{found.wrong} of {found.items}"
        ),
        cross_check(
            "Code-fix decision file, wrong picks",
            wrong_count(nightly["rule"]["wrong_pick"], nightly["items"]),
            found.wrong,
        ),
        recomputed("Code-fix precision (227 answered)", 0.978, precision, f"{precision:.4f}"),
        recomputed("Code-fix exact upper bound", 0.0126, exact, f"{exact:.4f}"),
        cross_check("Code-fix decision file, exact bound", nightly["wrong_exact_upper"], exact),
        verdict(
            "Code-fix reading (interval above 0, gain >= 0.05, bound < 5%)",
            "better",
            "better" if better else "not better",
        ),
    ]


def evolve_lines(name: str, file: str, key: str, claimed: tuple[float, float, float]) -> list[Line]:
    """One Evolve test: the mean and the map interval recomputed, the case interval stored."""
    body = load(file)[key]
    per_map = [value for _, value in sorted(body["per_map"].items())]
    mean = sum(per_map) / len(per_map)
    low, high = bootstrap_mean_interval(per_map, EVOLVE_SEED)
    case_low = body["case_interval"][0]
    reading = "better" if low > 0 and case_low > 0 else "not better"
    why = "per-case scores are not committed; the map interval above is recomputed"
    return [
        recomputed(f"{name} mean difference", claimed[0], mean, f"{mean:.4f}"),
        recomputed(f"{name} map interval, low end", claimed[1], low, f"{low:.4f}"),
        recomputed(f"{name} map interval, high end", claimed[2], high, f"{high:.4f}"),
        file_only(f"{name} case interval, low end", case_low, why),
        verdict(f"{name} reading (both interval low ends above 0)", "better", reading),
    ]


def prereg_hash_line() -> Line:
    """The Evolve result names the SHA-256 of the prereg it was scored under; compare it."""
    named = load("evolve-confirm.json")["prereg_sha256"]
    path = ROOT / "prereg" / "2026-11-01-evolve-final-card-confirm.md"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    status = Status.PASS if named == actual else Status.MISMATCH
    return Line("Evolve tested-card prereg file hash", named[:12], actual[:12], status)


def core_v3_one() -> list[Line]:
    """Core v3.1, stopped early; the counts fix each task's difference at -0.5 or 0."""
    body = load("core-v3-stopped-final.json")
    tasks = body["complete_blocks"]
    better, worse, same = body["tasks_better_worse_same"]
    mean = body["solve_rate"]["V3"] - body["solve_rate"]["P"]
    diffs = [-0.5] * worse + [0.0] * (same + better)
    consistent = better == 0 and abs(sum(diffs) / tasks - mean) < 1e-9
    low, high = bootstrap_mean_interval(diffs, CORE_V3_SEED)
    sound = "per-task differences are fixed by the committed counts and solve rates"
    if not consistent:
        sound = "MISMATCH: the committed counts do not fix the per-task differences"
    return [
        recomputed("Core v3.1 V3 minus plain", -0.054, mean, f"{mean:.4f}"),
        recomputed("Core v3.1 interval, low end", -0.108, low, f"{low:.4f}"),
        recomputed("Core v3.1 interval, high end", -0.014, high, f"{high:.4f}"),
        verdict(
            "Core v3.1 reading (upper bound below 0)",
            "V3 solves fewer",
            "V3 solves fewer" if high < 0 else "no detected difference",
        ),
        Line(
            "Core v3.1 recomputation premise",
            "-",
            "-",
            Status.PASS if consistent else Status.MISMATCH,
            sound,
        ),
    ]


def all_lines() -> list[Line]:
    """Every headline claim, in the order REPRODUCE.md lists them."""
    return [
        *plug_round_four(),
        *code_fix_study(),
        *evolve_lines(
            "Evolve tested card",
            "evolve-confirm.json",
            "primary_generated_final_vs_none",
            (0.168, 0.063, 0.274),
        ),
        prereg_hash_line(),
        *evolve_lines(
            "Evolve replication",
            "evolve-replication.json",
            "primary_fitness_final_vs_none",
            (0.160, 0.106, 0.218),
        ),
        *core_v3_one(),
    ]


def report(lines: list[Line]) -> None:
    """Print the table and the tally."""
    sys.stdout.write(f"{'status':9} {'claim':62} {'claimed':>9} {'found':>12}\n")
    for line in lines:
        sys.stdout.write(
            f"{line.status.value:9} {line.claim:62} {line.claimed:>9} {line.found:>12}\n"
        )
        if line.note:
            sys.stdout.write(f"{'':9}   note: {line.note}\n")
    tally = {status: sum(line.status is status for line in lines) for status in Status}
    sys.stdout.write(
        f"\n{tally[Status.PASS]} recomputed and equal, {tally[Status.STORED]} stored in committed "
        f"files but not recomputable, {tally[Status.MISMATCH]} MISMATCH\n"
    )


def main() -> int:
    """Print the report; non-zero when any claim and its files disagree."""
    lines = all_lines()
    report(lines)
    return 1 if any(line.status is Status.MISMATCH for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
