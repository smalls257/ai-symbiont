"""Tier 3, step 1: fetch pydantic and moto SWE-smith trajectories at a pinned revision.

The revision is pinned by commit and only the two repositories are read (DuckDB range requests).
Output files are refused unless their SHA-256 matches `results/repro-swe-smith-pins.json`.
The dataset is MIT licensed (dataset card); its bugs are synthetic and injected. Data stays in
the gitignored output directory.
Usage: uv run --with duckdb python scripts/reproduce/fetch_swe_smith.py --out DIR
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "routea"))

from plug_r4_smith_read import SPLITS, row_of  # noqa: E402

DATASET = "SWE-bench/SWE-smith-trajectories"
PINS = ROOT / "results" / "repro-swe-smith-pins.json"
REPOS = ("pydantic__pydantic", "getmoto__moto")
INSTANCE_REPO = re.compile(r"^(.+?)\.[0-9a-f]{8}\.")
FETCH_BATCH = 200


class PinMismatchError(RuntimeError):
    """A fetched file does not hash to what the pins say; the message names file and hashes."""


def load_pins() -> dict:
    """The committed pins: dataset revision and the SHA-256 of each per-repository file."""
    return json.loads(PINS.read_text())


def stream_rows(con, revision: str, split: str):
    """Yield (repo, row) for the wanted repositories of one split, in the study's JSON shape."""
    source = f"hf://datasets/{DATASET}@{revision}/data/{split}-*.parquet"
    marks = ",".join(f"'{repo}'" for repo in REPOS)
    query = (
        "select instance_id, traj_id, model, resolved, messages from read_parquet(?) "
        f"where regexp_extract(instance_id,'^(.+?)\\.[0-9a-f]{{8}}\\.',1) in ({marks})"
    )
    cursor = con.execute(query, [source])
    while batch := cursor.fetchmany(FETCH_BATCH):
        for fields in batch:
            yield INSTANCE_REPO.match(fields[0]).group(1), row_of(fields, split)


def fetch(revision: str, out: Path) -> dict[str, int]:
    """Write the per-repository JSONL files; returns the rows written per repository.

    Rows stay in the dataset's own order (splits tool, xml, ticks; shard order within a split):
    the item builder's output depends on it, so sorting here would change the pinned hashes.
    """
    import duckdb  # noqa: PLC0415 - only this step needs it

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    out.mkdir(parents=True, exist_ok=True)
    rows: dict[str, list[dict]] = {repo: [] for repo in REPOS}
    for split in SPLITS:
        for repo, row in stream_rows(con, revision, split):
            rows[repo].append(row)
    for repo, found in rows.items():
        (out / f"{repo}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in found))
    return {repo: len(found) for repo, found in rows.items()}


def verify(out: Path, pins: dict) -> dict[str, str]:
    """Hash each fetched file; raises PinMismatchError on the first one that differs."""
    seen = {}
    for repo in REPOS:
        digest = hashlib.sha256((out / f"{repo}.jsonl").read_bytes()).hexdigest()
        wanted = pins["raw_sha256"][repo]
        if digest != wanted:
            raise PinMismatchError(f"{repo}.jsonl is {digest}, the pins say {wanted}")
        seen[repo] = digest
    return seen


def main() -> int:
    """Fetch at the pinned revision and verify; exit 1 with the reason on a mismatch."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pins = load_pins()
    counts = fetch(pins["dataset_revision"], args.out)
    sys.stdout.write(f"fetched rows per repository: {counts}\n")
    try:
        verify(args.out, pins)
    except PinMismatchError as failed:
        sys.stderr.write(f"FAIL: {failed}\n")
        return 1
    sys.stdout.write("PASS: both files match results/repro-swe-smith-pins.json\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
