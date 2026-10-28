"""Export the T48 confirm repositories with the pinned T46 exporter, unchanged (counts only).

The confirm set was declared in commit 47a3a4f (docs/design/2026-10-28-fly-ablation.md), before
any T47 ablation run, from trajectory counts alone: the next three largest repositories of
nebius/SWE-rebench-openhands-trajectories after the T46 held-out three, sqlglot, the unreadable
four and the 100-repository pool. This driver calls `export_nebius_repos.export_held_out` (the
code of commit d860b8e: pinned dataset revisions, every task, SWE-rebench metadata, refused rows
counted) with that module's held-out list pointed at the confirm set, so the export code that
T46 froze is the export code here. It prints counts only; no row text.

    python scripts/datasets/export_confirm_repos.py --out-dir data/nebius-openhands/confirm

Periphery: needs the network and duckdb (the export-only venv).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_nebius_repos as pinned  # noqa: E402

CONFIRM = ("tox-dev/tox", "dask/dask", "pybamm-team/PyBaMM")


def main() -> None:
    """Point the pinned exporter's held-out list at the confirm set and export it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    overlap = set(CONFIRM) & (set(pinned.HELD_OUT) | {"tobymao/sqlglot"})
    if overlap:
        raise SystemExit(f"confirm repositories {sorted(overlap)} are already held out elsewhere")
    pinned.HELD_OUT = CONFIRM  # export_held_out and write_meta read this module global
    pinned.export_held_out(args)


if __name__ == "__main__":
    main()
