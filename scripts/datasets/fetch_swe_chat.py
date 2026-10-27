# /// script
# dependencies = ["duckdb>=1.1", "huggingface_hub>=0.25"]
# ///
"""Fetch a repo-scoped subset of the gated SALT-NLP/SWE-chat dataset (ODC-BY).

Violation prevented: Silent Fallback and privacy leakage. Every step either
produces the file it promises or raises; only schemas and counts are ever
printed. Raw rows (real people's prompts) are written only under --dest, which
must be a git-ignored data/ directory inside the repo, or an explicit absolute
path outside any git repo; anything else is refused. The dataset revision is
resolved once, pinned in <dest>/REVISION and reused by every subcommand.

The token comes from the HF_TOKEN environment variable only.

Subcommands:
  small    download README.md and every small top-level parquet file
  survey   per-repo session / user-prompt / pushback-label counts (counts only)
  export   stage conversations/commits one at a time, slice per repo, delete the stage
           (commit patches dropped; peak disk about 6.5 GB)
  manifest write MANIFEST.json (counts, sizes, revision, licence, date; no text)
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import time

DATASET = "SALT-NLP/SWE-chat"
SMALL_FILES = [
    "README.md",
    "sessions.parquet",
    "repositories.parquet",
    "session_logs.parquet",
    "checkpoints.parquet",
    "context_events.parquet",
    "skill_definitions.parquet",
    "skill_invocations.parquet",
    "subagent_tasks.parquet",
    "conversations_subagents.parquet",
]
PERMISSIVE = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC")
LABELS = ("correction", "rejection", "failure_report")
FIRST_REPO = "dayhaysoos/nimbus"
EXTRA_REPOS = 4


RATE_LIMIT_ATTEMPTS = 5
RATE_LIMIT_BASE_SECONDS = 15
RATE_LIMIT_CAP_SECONDS = 300
PIN_FILE = "REVISION"


class RateLimitExhaustedError(RuntimeError):
    """HF kept answering 429 after every bounded retry."""


def token() -> str:
    tok = os.environ.get("HF_TOKEN", "")
    if not tok:
        sys.exit("HF_TOKEN is not set; read it from the token file in the remote shell")
    return tok


def is_rate_limited(exc: Exception) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 429 or ("429" in str(exc) and "Too Many Requests" in str(exc))


def hf_api():
    from huggingface_hub import HfApi

    return HfApi(token=token())


def hf_fetch():
    from huggingface_hub import hf_hub_download

    return hf_hub_download


def retry_after_seconds(exc: Exception, attempt: int) -> float:
    """Wait time before retry; a Retry-After hint above the cap is a loud failure."""
    header = getattr(getattr(exc, "response", None), "headers", {}) or {}
    raw = header.get("Retry-After")
    hinted = 0.0
    if raw is not None:
        try:
            hinted = float(raw)
        except ValueError:
            hinted = math.nan
        if not math.isfinite(hinted) or hinted < 0:
            print(f"ignoring malformed Retry-After header {raw!r}", file=sys.stderr, flush=True)
            hinted = 0.0
    if hinted > RATE_LIMIT_CAP_SECONDS:
        raise RateLimitExhaustedError(
            f"HF asked to wait {hinted:.0f}s, above the {RATE_LIMIT_CAP_SECONDS}s cap; rerun later"
        ) from exc
    backoff = min(RATE_LIMIT_BASE_SECONDS * 2**attempt, RATE_LIMIT_CAP_SECONDS)
    return max(hinted, backoff)


def with_backoff(label, call, sleep=time.sleep, attempts=RATE_LIMIT_ATTEMPTS):
    """Run call(); on HTTP 429 wait and retry a bounded number of times, then fail loudly."""
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            if not is_rate_limited(exc):
                raise
            wait = retry_after_seconds(exc, attempt)
            print(
                f"HF rate limit (429) on {label}; attempt {attempt + 1}/{attempts}, "
                f"waiting {wait:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            if attempt + 1 == attempts:
                raise RateLimitExhaustedError(
                    f"HF kept rate-limiting {label} after {attempts} attempts; "
                    "wait a few minutes and rerun"
                ) from exc
            sleep(wait)
    raise AssertionError("attempts must be at least 1")


def clean_git_env() -> dict[str, str]:
    """Environment without GIT_* so a hook's GIT_DIR cannot redirect the probe."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {**env, "LC_ALL": "C"}


def check_dest(dest: pathlib.Path) -> pathlib.Path:
    """Refuse any destination that could put raw rows where git would track them."""
    anchor = dest.resolve()
    while not anchor.exists():
        anchor = anchor.parent
    probe = subprocess.run(
        ["git", "-C", str(anchor), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        env=clean_git_env(),
    )
    if probe.returncode != 0:
        if "not a git repository" not in probe.stderr:
            sys.exit(f"refusing --dest {dest}: git failed: {probe.stderr.strip()}")
        if not dest.is_absolute():
            sys.exit(f"refusing --dest {dest}: outside a git repo it must be an absolute path")
        return dest
    top = pathlib.Path(probe.stdout.strip()).resolve()
    inside = dest.resolve().relative_to(top)
    ignored = subprocess.run(
        ["git", "-C", str(top), "check-ignore", "-q", str(inside / "probe")],
        env=clean_git_env(),
    ).returncode
    if inside.parts[:1] != ("data",) or ignored != 0:
        sys.exit(f"refusing --dest {dest}: inside a repo it must sit under a git-ignored data/")
    return dest


def secure_tree(dest: pathlib.Path) -> None:
    """Directories 0700, files 0600, including ones that already existed."""
    dest.chmod(0o700)
    for path in dest.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)


def pinned_revision(dest: pathlib.Path, requested: str | None) -> str:
    """Resolve the dataset revision once; every later subcommand reuses the pin."""
    pin = dest / PIN_FILE
    pinned = pin.read_text().strip() if pin.exists() else None
    if pinned and requested and pinned != requested:
        sys.exit(f"--revision {requested} conflicts with pinned {pinned} in {pin}")
    rev = (
        requested
        or pinned
        or with_backoff("dataset_info", lambda: hf_api().dataset_info(DATASET).sha)
    )
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    pin.write_text(rev + "\n")
    return rev


def remote_con(rev: str):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("CREATE SECRET hf (TYPE HUGGINGFACE, TOKEN ?)", [token()])
    con.execute("SET http_retries=8; SET http_retry_wait_ms=2000;")
    return con


def hf_url(rev: str, name: str) -> str:
    return f"hf://datasets/{DATASET}@{rev}/{name}"


def download(name: str, local_dir: pathlib.Path, rev: str) -> str:
    return with_backoff(
        name,
        lambda: hf_fetch()(
            DATASET,
            name,
            repo_type="dataset",
            token=token(),
            local_dir=str(local_dir),
            revision=rev,
        ),
    )


def cmd_small(dest: pathlib.Path, rev: str) -> None:
    for name in SMALL_FILES:
        download(name, dest, rev)
        print(f"downloaded {name}")


def selected_repos(dest: pathlib.Path) -> list[str]:
    """FIRST_REPO plus the busiest other permissive repos; FIRST_REPO must be permissive too."""
    import duckdb

    marks = ",".join("?" * len(PERMISSIVE))
    table = f"'{dest}/repositories.parquet'"
    first = duckdb.execute(
        f"SELECT license_type FROM {table} WHERE repo_id=?", [FIRST_REPO]
    ).fetchall()
    if not first or first[0][0] not in PERMISSIVE:
        found = first[0][0] if first else "absent from repositories.parquet"
        sys.exit(f"{FIRST_REPO} is not permissively licensed ({found}); refusing to export it")
    rows = duckdb.execute(
        f"SELECT repo_id FROM {table} "
        f"WHERE license_type IN ({marks}) AND repo_id <> ? "
        f"ORDER BY num_sessions DESC LIMIT {EXTRA_REPOS}",
        [*PERMISSIVE, FIRST_REPO],
    ).fetchall()
    return [FIRST_REPO] + [r[0] for r in rows]


def cmd_survey(dest: pathlib.Path, rev: str) -> None:
    con = remote_con(rev)
    repos = selected_repos(dest)
    marks = ",".join("?" * len(repos))
    rows = with_backoff(
        "survey query",
        lambda: con.execute(
            "SELECT repo_id, count(DISTINCT session_id) sessions, count(*) prompts, "
            "count(*) FILTER (WHERE prompt_pushback IS NOT NULL) annotated, "
            + ", ".join(f"count(*) FILTER (WHERE prompt_pushback='{x}') {x}" for x in LABELS)
            + f" FROM read_parquet('{hf_url(rev, 'conversations.parquet')}') "
            f"WHERE turn_type='user_prompt' AND repo_id IN ({marks}) GROUP BY 1 ORDER BY 2 DESC",
            repos,
        ).fetchall(),
    )
    print("repo, sessions_with_prompts, prompts, annotated, correction, rejection, failure_report")
    for r in rows:
        print(r)


def export_table(
    dest: pathlib.Path, rev: str, name: str, repos: list[str], select: str
) -> list[pathlib.Path]:
    """Stage a big parquet locally (ranged reads hit the HF 429 quota), slice, delete.

    The stage holds raw conversation rows, so it is removed even when a step fails,
    and slices written by a failed run are removed with it.
    """
    import duckdb

    stage = dest / ".staging"
    out_dir = dest / name
    written: list[pathlib.Path] = []
    stage.mkdir(mode=0o700, exist_ok=True)
    out_dir.mkdir(mode=0o700, exist_ok=True)
    try:
        local = download(f"{name}.parquet", stage, rev)
        for repo in repos:
            out = out_dir / (repo.replace("/", "__") + ".parquet")
            written.append(out)
            duckdb.execute(
                f"COPY (SELECT {select} FROM read_parquet('{local}') WHERE repo_id=?) "
                f"TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)",
                [repo],
            )
            print(f"{name} {repo}: wrote {out.name}", flush=True)
        return written
    except BaseException:
        for partial in written:
            partial.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def cmd_export(dest: pathlib.Path, rev: str) -> None:
    repos = selected_repos(dest)
    conversations = export_table(dest, rev, "conversations", repos, "*")
    try:
        export_table(dest, rev, "commits", repos, "* EXCLUDE (patch)")
    except BaseException:
        for sliced in conversations:
            sliced.unlink(missing_ok=True)
        raise


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def cmd_manifest(dest: pathlib.Path, rev: str) -> None:
    import duckdb

    files = []
    for p in sorted(dest.rglob("*")):
        if not p.is_file() or ".cache" in p.parts or p.name == "MANIFEST.json":
            continue
        entry = {"path": str(p.relative_to(dest)), "bytes": p.stat().st_size, "sha256": sha256(p)}
        if p.suffix == ".parquet":
            entry["rows"] = duckdb.execute(f"SELECT count(*) FROM '{p}'").fetchone()[0]
        files.append(entry)
    manifest = {
        "dataset": DATASET,
        "revision": rev,
        "licence": "ODC-BY",
        "downloaded": datetime.date.today().isoformat(),
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    print(f"manifest: {len(files)} files, {manifest['total_bytes']} bytes")


COMMANDS = {
    "small": cmd_small,
    "survey": cmd_survey,
    "export": cmd_export,
    "manifest": cmd_manifest,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--dest", type=pathlib.Path, required=True)
    ap.add_argument(
        "--revision", default=None, help="dataset commit sha; default: the pin, else current head"
    )
    args = ap.parse_args()
    dest = check_dest(args.dest)
    try:
        rev = pinned_revision(dest, args.revision)
        COMMANDS[args.command](dest, rev)
    except RateLimitExhaustedError as exc:
        sys.exit(str(exc))
    finally:
        if dest.exists():
            secure_tree(dest)


if __name__ == "__main__":
    main()
