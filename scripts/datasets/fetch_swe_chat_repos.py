# /// script
# dependencies = ["duckdb>=1.1", "huggingface_hub>=0.25"]
# ///
"""Fetch Claude Code sessions of named SWE-chat repos, with correction labels on them.

Reads only (session_id, source_entry_uuid, prompt_pushback) from conversations.parquet and
writes each label onto the user event whose uuid matches. Needs `fetch_swe_chat.py small`
in --dest first. Output: <dest>/repos/<repo name>/<session_id>.jsonl; prints counts only.
Unknown or non-permissive repos exit loudly.
"""

import argparse
import json
import pathlib
import shutil
import sys

from fetch_swe_chat import (
    DATASET,
    PERMISSIVE,
    RateLimitExhaustedError,
    check_dest,
    hf_url,
    pinned_revision,
    remote_con,
    secure_tree,
    token,
    with_backoff,
)

STAGE = ".transcripts-stage"
DOWNLOAD_WORKERS = 8


def claude_sessions(dest: pathlib.Path, names: list[str]) -> list[tuple[str, str, str, str]]:
    """(repo name, repo_id, session_id, transcript_path) of the named repos' Claude sessions."""
    import duckdb

    repos = duckdb.execute(
        f"SELECT name, repo_id, license_type FROM '{dest}/repositories.parquet' "
        f"WHERE name IN ({','.join('?' * len(names))})",
        names,
    ).fetchall()
    unknown = sorted(set(names) - {r[0] for r in repos})
    if unknown:
        sys.exit(f"unknown repo name(s) in repositories.parquet: {', '.join(unknown)}")
    for name, _repo_id, license in repos:
        if license not in PERMISSIVE:
            sys.exit(f"{name} is not permissively licensed ({license}); refusing to fetch it")
    by_id = {r[1]: r[0] for r in repos}
    rows = duckdb.execute(
        f"SELECT repo_id, session_id, transcript_path FROM '{dest}/sessions.parquet' "
        f"WHERE agent ILIKE '%claude%' AND repo_id IN ({','.join('?' * len(by_id))}) "
        "ORDER BY repo_id, session_id",
        list(by_id),
    ).fetchall()
    return [(by_id[rid], rid, sid, path) for rid, sid, path in rows]


def download_transcripts(paths: list[str], local_dir: pathlib.Path, rev: str) -> None:
    from huggingface_hub import snapshot_download

    with_backoff(
        "transcripts",
        lambda: snapshot_download(
            DATASET,
            repo_type="dataset",
            revision=rev,
            token=token(),
            local_dir=str(local_dir),
            allow_patterns=paths,
            max_workers=DOWNLOAD_WORKERS,
        ),
    )


def fetch_labels(rev: str, repo_ids: list[str]) -> list[tuple[str, str, str]]:
    """(session_id, source_entry_uuid, label); reads three columns only."""
    con = remote_con(rev)
    marks = ",".join("?" * len(repo_ids))
    return with_backoff(
        "label query",
        lambda: con.execute(
            "SELECT session_id, source_entry_uuid, prompt_pushback "
            f"FROM read_parquet('{hf_url(rev, 'conversations.parquet')}') "
            "WHERE turn_type='user_prompt' AND prompt_pushback IS NOT NULL "
            f"AND repo_id IN ({marks})",
            repo_ids,
        ).fetchall(),
    )


def label_line(line: bytes, labels: dict[str, str]) -> bytes | None:
    """The line with its label set, or None when no label applies (line stays as is)."""
    if not line.startswith(b"{"):
        return None
    event = json.loads(line)
    label = labels.get(event.get("uuid")) if event.get("type") == "user" else None
    if label is None:
        return None
    event["prompt_pushback"] = label
    return json.dumps(event, ensure_ascii=False).encode()


def place_labels(path: pathlib.Path, labels: dict[str, str]) -> int:
    """Write labels onto user events by uuid; every other line stays byte-identical."""
    lines = path.read_bytes().split(b"\n")
    placed = 0
    for i, line in enumerate(lines):
        labeled = label_line(line, labels)
        if labeled is not None:
            lines[i] = labeled
            placed += 1
    path.write_bytes(b"\n".join(lines))
    return placed


def move_into_place(dest: pathlib.Path, sessions: list[tuple[str, str, str, str]]) -> None:
    for name, _rid, sid, rel in sessions:
        target = dest / "repos" / name / f"{sid}.jsonl"
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.move(str(dest / STAGE / rel), target)


def place_all(dest: pathlib.Path, sessions, rows) -> tuple[int, int]:
    """(labels wanted, labels placed) over every fetched session."""
    fetched = {s[2] for s in sessions}
    wanted = {(sid, uuid): label for sid, uuid, label in rows if sid in fetched}
    placed = 0
    for name, _rid, sid, _rel in sessions:
        own = {uuid: lab for (s, uuid), lab in wanted.items() if s == sid}
        placed += place_labels(dest / "repos" / name / f"{sid}.jsonl", own)
    return len(wanted), placed


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", type=pathlib.Path, required=True)
    ap.add_argument("--repos", nargs="+", required=True, metavar="NAME")
    args = ap.parse_args(argv)
    dest = check_dest(args.dest)
    stage = dest / STAGE
    try:
        rev = pinned_revision(dest, None)
        sessions = claude_sessions(dest, args.repos)
        download_transcripts([s[3] for s in sessions], stage, rev)
        move_into_place(dest, sessions)
        rows = fetch_labels(rev, sorted({s[1] for s in sessions}))
        wanted, placed = place_all(dest, sessions, rows)
    except RateLimitExhaustedError as exc:
        sys.exit(str(exc))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if dest.exists():
            secure_tree(dest)
    print(f"sessions {len(sessions)}, labels wanted {wanted}, labels placed {placed}")


if __name__ == "__main__":
    main()
