# /// script
# requires-python = ">=3.12"
# dependencies = ["duckdb>=1.1"]
# ///
"""Export the tobymao/sqlglot rows of nebius/SWE-rebench-openhands-trajectories
to data/nebius-openhands/sqlglot.jsonl, the JSONL shape the OpenHands reader takes.

Periphery, not core: it touches the network. Run from the repo root:

    uv run scripts/datasets/export_nebius_sqlglot.py

Sparing with Hugging Face, which rate-limits anonymous access (HTTP 429):
one cheap pass reads only the `repo` column to find which parquet files hold
sqlglot rows, then one pass reads the needed columns from those files only.
A token is used if one is set (HF_TOKEN, or ~/.cache/huggingface/token).
On 429 it waits and retries a bounded number of times, saying so each time,
then stops with a non-zero exit and what to do; it never loops and never
writes a partial file. The finished file is read back through the OpenHands
reader so a bad export fails here, not in the miner.
"""

import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from symbiont.readers import openhands  # noqa: E402

DATASET = "nebius/SWE-rebench-openhands-trajectories"
REPO = "tobymao/sqlglot"
PARQUET_GLOB = f"hf://datasets/{DATASET}/**/*.parquet"
OUT = REPO_ROOT / "data" / "nebius-openhands" / "sqlglot.jsonl"
TOKEN_FILE = Path.home() / ".cache" / "huggingface" / "token"
# `tools` (the tool schema, identical in every row) is left out on purpose.
COLUMNS = "trajectory_id, instance_id, repo, trajectory, model_patch, exit_status, resolved"
RATE_LIMIT_WAITS_S = (30, 90)  # then stop: a third 429 means access is blocked for now


@dataclass(frozen=True)
class Counts:
    rows: int
    tasks: int
    records: int


def find_token(env: Mapping[str, str], token_file: Path) -> str | None:
    if env.get("HF_TOKEN"):
        return env["HF_TOKEN"]
    if token_file.is_file():
        return token_file.read_text().strip() or None
    return None


def is_rate_limited(exc: BaseException) -> bool:
    text = str(exc)
    return "429" in text or "Too Many Requests" in text


def check_export(path: Path) -> Counts:
    """Reads the export back with the OpenHands reader; raises ReadError naming
    the line if any row is unreadable, and exits if there are no rows at all."""
    sessions, tasks, records = set(), set(), 0
    for record in openhands.read(path, REPO):
        sessions.add(record.session_id)
        tasks.add(record.task_id)
        records += 1
    if not sessions:
        raise SystemExit(f"{path}: no rows exported; refusing to call this a dataset")
    return Counts(rows=len(sessions), tasks=len(tasks), records=records)


def _with_rate_limit_backoff(what: str, run):
    for attempt, wait in enumerate((*RATE_LIMIT_WAITS_S, None), start=1):
        try:
            return run()
        except Exception as exc:  # duckdb raises its own HTTP exception types
            if not is_rate_limited(exc):
                raise
            if wait is None:
                raise SystemExit(
                    f"{what}: Hugging Face is rate-limiting this machine (HTTP 429) after "
                    f"{attempt} attempts. Stopped. Put a token in {TOKEN_FILE} or HF_TOKEN, "
                    "or try again later."
                ) from exc
            print(
                f"{what}: HTTP 429 (rate-limited), attempt {attempt}; waiting {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
    raise AssertionError("unreachable: the last attempt raises SystemExit or returns")


def _connect():
    import duckdb

    db = duckdb.connect()
    token = find_token(os.environ, TOKEN_FILE)
    if token:
        db.execute("CREATE SECRET hf (TYPE HUGGINGFACE, TOKEN ?)", [token])
    print(f"Hugging Face access: {'token' if token else 'anonymous'}", file=sys.stderr)
    return db


def _files_with_repo(db) -> list[str]:
    rows = db.execute(
        f"SELECT filename, count(*) FROM read_parquet('{PARQUET_GLOB}', filename=true) "
        "WHERE repo = ? GROUP BY filename ORDER BY filename",
        [REPO],
    ).fetchall()
    for name, n in rows:
        print(f"  {n:5d} rows in {name}", file=sys.stderr)
    return [name for name, _ in rows]


def _export(db, files: list[str], out: Path) -> None:
    file_list = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
    db.execute(
        f"COPY (SELECT {COLUMNS} FROM read_parquet([{file_list}]) WHERE repo = ? "
        f"ORDER BY instance_id, trajectory_id) TO '{out}' (FORMAT JSON)",
        [REPO],
    )


def main() -> int:
    db = _connect()
    files = _with_rate_limit_backoff("finding sqlglot rows", lambda: _files_with_repo(db))
    if not files:
        raise SystemExit(f"no rows with repo = {REPO!r} in {DATASET}; has the dataset changed?")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    partial = OUT.with_suffix(".jsonl.partial")
    _with_rate_limit_backoff("exporting sqlglot rows", lambda: _export(db, files, partial))
    counts = check_export(partial)
    partial.replace(OUT)
    print(f"{OUT}: {counts.rows} trajectories, {counts.tasks} tasks, {counts.records} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
