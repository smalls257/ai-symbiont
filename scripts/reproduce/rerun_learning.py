"""Tier 3 of REPRODUCE.md: rebuild the code-fix study's data from public sources, judge a rerun.

Stages: `data` (fetch, mine, require every hash to match its pin), `prerequisites` (check the
artifacts the learning stage cannot rebuild; exit 3 when missing), `compare FILE` (a rerun's
decision file against the committed one, inside stated bands).
Usage: uv run --with duckdb python scripts/reproduce/rerun_learning.py data --work DIR
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import rescore
from exact_bounds import clopper_pearson_upper

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
SCRIPTS = ROOT / "scripts"
EXIT_MISSING_PREREQUISITE = 3
# prereg/2026-10-31-code-fix-lessons.md, power section: the exact bound stays under 5% while
# at most 33 of the 924 answers are wrong.
MOST_WRONG = 33
WRONG_BAR = 0.05
CHOSEN = ["pydantic__pydantic", "getmoto__moto"]
FRESH_BUILD = (
    "primary-items.jsonl",
    "primary-queries.jsonl",
    "primary-negatives.txt",
)


def sha256_of(path: Path) -> str:
    """SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def announce(line: str) -> None:
    """One progress line."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def require_equal(label: str, found: str, pinned: str) -> None:
    """Raise SystemExit naming the file when a hash differs from its pin."""
    if found != pinned:
        raise SystemExit(f"FAIL: {label} is {found}, the pins say {pinned}")
    announce(f"  ok  {label}")


def step(words: list[str]) -> None:
    """Run one command of the study; a failure stops the stage with its status."""
    done = subprocess.run(words, cwd=ROOT, check=False)
    if done.returncode != 0:
        raise SystemExit(f"FAIL: {' '.join(words[:4])} exited {done.returncode}")


def fetch_raw_rows(work: Path) -> None:
    """Fetch only the two repositories' rows at the pinned revision; the fetch verifies them."""
    announce("1. fetch the pinned dataset revision (only pydantic and moto rows)")
    step(
        ["uv", "run", "--with", "duckdb", "python", "scripts/reproduce/fetch_swe_smith.py"]
        + ["--out", str(work / "raw")]
    )


def mine_items(work: Path, chosen: Path, study: dict) -> None:
    """Build the 924 items with the study's code and require its pinned hashes."""
    announce("2. mine the items with the study's code")
    builder = [sys.executable, "scripts/routea/plug_r4_smith.py"]
    step(
        [*builder, "build", "--raw", str(work / "raw"), "--repos", str(chosen)]
        + ["--out", str(work / "items")]
    )
    for name in FRESH_BUILD:
        require_equal(f"items/{name}", sha256_of(work / "items" / name), study["files"][name])


def mine_nightly_inputs(work: Path, chosen: Path, pins: dict) -> None:
    """Build the history lessons and pairs the nightly arm learns from; require their hashes."""
    announce("3. mine the nightly arm's history lessons and pairs")
    step(
        [
            sys.executable,
            "scripts/routea/plug_r4_smith.py",
            "prep",
            "--raw",
            str(work / "raw"),
            "--repos",
            str(chosen),
            "--out",
            str(work / "prep"),
        ]
    )
    for name, wanted in pins["prep_sha256"].items():
        require_equal(f"prep/{name}", sha256_of(work / "prep" / name), wanted)


def rebuild_study_inputs(work: Path) -> None:
    """Fetch, mine and build with the study's code; every output is checked against the pins."""
    started = time.monotonic()
    pins = json.loads((RESULTS / "repro-swe-smith-pins.json").read_text())
    study = json.loads((RESULTS / "plug-r4-smith-pins.json").read_text())
    work.mkdir(parents=True, exist_ok=True)
    chosen = work / "chosen.json"
    chosen.write_text(json.dumps(CHOSEN))
    fetch_raw_rows(work)
    mine_items(work, chosen, study)
    mine_nightly_inputs(work, chosen, pins)
    announce(f"PASS: data stage reproduced byte for byte ({time.monotonic() - started:.0f}s)")


def prerequisites_stage(items: Path, artifacts: Path) -> int:
    """Check the inputs the learning stage cannot rebuild; 0 when complete, 3 when not."""
    sys.path.insert(0, str(SCRIPTS / "routea"))
    sys.path.insert(0, str(ROOT / "src"))
    from plug_r4_scored import PinMismatchError  # noqa: PLC0415
    from plug_r4_smith_decide import check  # noqa: PLC0415

    selections = [RESULTS / "plug-r4-selection.json", RESULTS / "plug-r4-selection-nightly.json"]
    adapters = artifacts / "plug-r3-run" / "adapters"
    try:
        check(items, adapters, selections, RESULTS / "plug-r4-smith-pins.json")
    except (PinMismatchError, OSError) as missing:
        sys.stderr.write(
            f"NOT RUN: {missing}\nsee REPRODUCE.md, tier 3, what the learning stage needs\n"
        )
        return EXIT_MISSING_PREREQUISITE
    announce("PASS: items, round 3 judge adapters and selections match the study's pins")
    return 0


def band_lines(rerun: dict, committed: dict) -> list[tuple[str, str, bool]]:
    """(name, shown, inside the band) for each stated band; see REPRODUCE.md for where from."""
    new, old = rerun["nightly_vs_agree"], committed["nightly_vs_agree"]
    wrong = round(new["rule"]["wrong_pick"] * new["items"])
    exact = clopper_pearson_upper(wrong, new["items"])
    low, high = old["gain_interval"]
    return [
        (
            "nightly coverage inside the committed interval",
            f"{new['coverage_rule']:.4f} in [{low}, {high}]",
            low <= new["coverage_rule"] <= high,
        ),
        (f"wrong picks at most {MOST_WRONG} of {new['items']}", f"{wrong}", wrong <= MOST_WRONG),
        (f"exact upper bound under {WRONG_BAR}", f"{exact:.4f}", exact < WRONG_BAR),
        (
            "agree rule answers nothing here (committed: 0 answered)",
            f"{rerun['agree_vs_judge_alone']['rule']['answered']} answered",
            rerun["agree_vs_judge_alone"]["rule"]["answered"] == old_answered(committed),
        ),
    ]


def judge_band_lines(rerun: dict, committed: dict) -> list[tuple[str, str, bool]]:
    """(name, shown, inside) for the judge arms: they must reproduce the committed numbers."""
    new, old = rerun["agree_vs_judge_alone"], committed["agree_vs_judge_alone"]
    return [
        (
            "agree rule answers what the committed run answered",
            f"{new['rule']['answered']} vs {old['rule']['answered']}",
            new["rule"]["answered"] == old["rule"]["answered"],
        ),
        (
            "judge alone answers what the committed run answered",
            f"{new['judge_alone']['answered']} vs {old['judge_alone']['answered']}",
            new["judge_alone"]["answered"] == old["judge_alone"]["answered"],
        ),
        (
            "coverage of both arms equals the committed value",
            f"{new['coverage_rule']} and {new['coverage_judge_alone']}",
            (new["coverage_rule"], new["coverage_judge_alone"])
            == (old["coverage_rule"], old["coverage_judge_alone"]),
        ),
        (
            "reading is the committed one",
            f"{new['reading']} vs {old['reading']}",
            new["reading"] == old["reading"],
        ),
    ]


def old_answered(committed: dict) -> int:
    """How many items the agree rule answered in the committed decision."""
    return int(committed["agree_vs_judge_alone"]["rule"]["answered"])


def compare_stage(rerun_path: Path) -> int:
    """Print the bands for a rerun's decision file; 0 when every band holds, else 1.

    A file with a nightly arm gets the nightly bands; a judge-only rescore gets the judge bands.
    """
    committed = json.loads((RESULTS / "plug-r4-smith-decision.json").read_text())
    rerun = json.loads(rerun_path.read_text())
    judges_only = "nightly_vs_agree" not in rerun
    lines = judge_band_lines(rerun, committed) if judges_only else band_lines(rerun, committed)
    for name, shown, inside in lines:
        announce(f"{'IN BAND ' if inside else 'OUT OF BAND'}  {name}: {shown}")
    return 0 if all(inside for _, _, inside in lines) else 1


def main() -> int:
    """Dispatch the three stages."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    stages.add_parser("data").add_argument("--work", type=Path, required=True)
    needs = stages.add_parser("prerequisites")
    needs.add_argument("--items", type=Path, required=True)
    needs.add_argument("--artifacts", type=Path, required=True)
    stages.add_parser("compare").add_argument("rerun", type=Path)
    fetching = stages.add_parser("fetch-adapters")
    fetching.add_argument("--dest", type=Path, required=True)
    fetching.add_argument("--repo", help="OWNER/Llama-3.2-1B-symbiont-judge-adapters")
    scoring = stages.add_parser("rescore")
    for flag in ("items", "base", "adapters", "work"):
        scoring.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "data":
        rebuild_study_inputs(args.work)
        return 0
    if args.stage == "prerequisites":
        return prerequisites_stage(args.items, args.artifacts)
    if args.stage == "compare":
        return compare_stage(args.rerun)
    try:
        if args.stage == "fetch-adapters":
            rescore.fetch_adapters(args.dest, args.repo)
            announce("PASS: every adapter file matches its pin")
            return 0
        decision = rescore.rescore(args.items, args.base, args.adapters, args.work)
    except rescore.AdapterPinError as missing:
        sys.stderr.write(f"NOT RUN: {missing}\n")
        return EXIT_MISSING_PREREQUISITE
    return compare_stage(decision)


if __name__ == "__main__":
    sys.exit(main())
