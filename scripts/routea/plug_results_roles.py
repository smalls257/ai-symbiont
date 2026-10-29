"""Add the results gate's row keys to the Plug scored output (prereg amendment 1); no recomputing.

Usage: uv run python scripts/routea/plug_results_roles.py SCORED.json --out results/l2l-a2.json

Each row keeps its `row` and `label` and gains `arm` and `role`; the `control` label maps to role
`reference`. The untouched output's sha256 is recorded, so the file can be checked against it.
"""

import argparse
import hashlib
import json
from pathlib import Path

ROLE = {
    "floor": "floor",
    "reference": "reference",
    "under_test": "under_test",
    "control": "reference",
}


def with_roles(document: dict, scored_sha256: str) -> dict:
    """The scored document with `arm` and `role` on every row; raises on an unknown label."""
    rows = []
    for row in document["rows"]:
        if row["label"] not in ROLE:
            raise ValueError(f"row {row['row']} has label {row['label']!r}, which no role maps")
        rows.append({**row, "arm": row["row"], "role": ROLE[row["label"]]})
    return {**document, "rows": rows, "scored_output_sha256": scored_sha256}


def main() -> None:
    """Write the gate-shaped results file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scored", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.scored.read_bytes()
    document = with_roles(json.loads(raw), hashlib.sha256(raw).hexdigest())
    args.out.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
