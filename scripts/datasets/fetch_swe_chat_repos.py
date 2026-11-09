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
import collections
import json
import os
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
    for name, _repo_id, license_type in repos:
        if license_type not in PERMISSIVE:
            sys.exit(f"{name} is not permissively licensed ({license_type}); refusing to fetch it")
    by_id = {r[1]: r[0] for r in repos}
    rows = duckdb.execute(
        f"SELECT repo_id, session_id, transcript_path FROM '{dest}/sessions.parquet' "
        f"WHERE agent ILIKE '%claude%' AND repo_id IN ({','.join('?' * len(by_id))}) "
        "ORDER BY repo_id, session_id",
        list(by_id),
    ).fetchall()
    empty = sorted(set(by_id.values()) - {by_id[r[0]] for r in rows})
    if empty:
        sys.exit(f"no Claude Code sessions for repo(s): {', '.join(empty)}")
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
    uuid = event.get("uuid")
    label = labels.get(uuid) if event.get("type") == "user" and isinstance(uuid, str) else None
    if label is None:
        return None
    event["prompt_pushback"] = label
    return json.dumps(event, ensure_ascii=False).encode()


def place_labels(path: pathlib.Path, labels: dict[str, str]) -> int:
    """Write labels onto user events by uuid, atomically; other lines stay byte-identical.

    A malformed line stops the run naming file and line number, never its text.
    """
    lines = path.read_bytes().split(b"\n")
    placed = 0
    for number, line in enumerate(lines, start=1):
        try:
            labeled = label_line(line, labels)
        except json.JSONDecodeError:
            sys.exit(f"malformed JSON in {path} at line {number}")
        if labeled is not None:
            lines[number - 1] = labeled
            placed += 1
    if placed:
        temp = path.with_name(path.name + ".tmp")
        temp.write_bytes(b"\n".join(lines))
        os.replace(temp, path)
    return placed


def group_labels(rows: list[tuple[str, str, str]]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for sid, uuid, label in rows:
        grouped[sid][uuid] = label
    return grouped


def label_staged(
    stage: pathlib.Path, sessions: list[tuple[str, str, str, str]], rows: list[tuple[str, str, str]]
) -> tuple[int, int]:
    """(labels wanted, labels placed) over the staged transcripts of the fetched sessions."""
    grouped = group_labels(rows)
    placed = wanted = 0
    for _name, _rid, sid, rel in sessions:
        own = grouped.get(sid, {})
        wanted += len(own)
        placed += place_labels(stage / rel, own)
    return wanted, placed


def move_into_place(dest: pathlib.Path, sessions: list[tuple[str, str, str, str]]) -> None:
    """Publish labeled transcripts; runs only after every label step has succeeded."""
    for name, _rid, sid, rel in sessions:
        target = dest / "repos" / name / f"{sid}.jsonl"
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.move(str(dest / STAGE / rel), target)


def require_small_fetch(dest: pathlib.Path) -> None:
    if not (dest / "REVISION").exists():
        sys.exit(f"{dest / 'REVISION'} is missing: run fetch_swe_chat.py small first")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", type=pathlib.Path, required=True)
    ap.add_argument("--repos", nargs="+", required=True, metavar="NAME")
    args = ap.parse_args(argv)
    dest = check_dest(args.dest)
    stage = dest / STAGE
    try:
        require_small_fetch(dest)
        rev = pinned_revision(dest, None)
        sessions = claude_sessions(dest, args.repos)
        download_transcripts([s[3] for s in sessions], stage, rev)
        rows = fetch_labels(rev, sorted({s[1] for s in sessions}))
        wanted, placed = label_staged(stage, sessions, rows)
        move_into_place(dest, sessions)
    except RateLimitExhaustedError as exc:
        sys.exit(str(exc))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if dest.exists():
            secure_tree(dest)
    print(f"sessions {len(sessions)}, labels wanted {wanted}, labels placed {placed}")


if __name__ == "__main__":
    main()
