"""Read the AIDev v4 parquet tables (HF hao-li/AIDev, CC-BY-4.0, Hao Li et al., arXiv 2507.15003).

Periphery: duckdb over the local download, read-only. Commit order is `pr_commits` row order
(`file_row_number`, first row of a duplicated sha kept), which `order.py` checks. Patch text and
comment bodies are untrusted: they are parsed here and in the pure modules, never printed or
written out. A patch that does not parse becomes `hunks=None` (unknown) and is counted by the
caller, never read as "no change".
"""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import duckdb
from flags import Comment, Commit, FileState
from hunks import PatchError, anchor_line, parse_patch
from order import CommitFacts

FETCH_ROWS = 20_000


@dataclass(frozen=True)
class PrMeta:
    """What a PR is: its agent and repository."""

    agent: str
    repo: str
    language: str | None


@dataclass(frozen=True)
class RawComment:
    """A thread-opening inline comment; `body` and `diff_hunk` stay in memory only."""

    comment: Comment
    body: str
    diff_hunk: str


def connect(root: Path) -> duckdb.DuckDBPyConnection:
    """A connection with one view per table and the commit order table `c`."""
    con = duckdb.connect()
    for table in ("pull_request", "repository", "pr_commits", "pr_commit_details"):
        con.execute(f"create view {table} as select * from read_parquet('{root / table}.parquet')")
    con.execute(
        f"create view pr_review_comments as select * from "
        f"read_parquet('{root / 'pr_review_comments'}.parquet')"
    )
    con.execute(
        f"create view pr_reviews as select * from read_parquet('{root}/pr_reviews.parquet')"
    )
    con.execute(
        f"""create temp table c as select sha, pr_id, min(r) r, bool_or(plan) plan from (
          select sha, pr_id, file_row_number r, coalesce(message like 'Initial plan%', false) plan
          from read_parquet('{root}/pr_commits.parquet', file_row_number=true)) group by 1, 2"""
    )
    return con


def pr_meta(con: duckdb.DuckDBPyConnection) -> dict[int, PrMeta]:
    """Agent, repository name and language for every PR."""
    rows = con.execute(
        """select p.id, p.agent, r.full_name, r.language from pull_request p
           left join repository r on r.id = p.repo_id"""
    ).fetchall()
    return {pid: PrMeta(agent, repo or "unknown", language) for pid, agent, repo, language in rows}


def order_facts(con: duckdb.DuckDBPyConnection) -> Iterator[tuple[int, list[CommitFacts]]]:
    """Every PR's commits in row order, with file statuses but no patch text."""
    statuses: dict[str, dict[str, str]] = defaultdict(dict)
    for sha, name, status in con.execute(
        "select sha, filename, status from pr_commit_details where status is not null"
    ).fetchall():
        statuses[sha][name] = status
    by_pr: dict[int, list[CommitFacts]] = defaultdict(list)
    for pid, sha, plan in con.execute(
        "select pr_id, sha, plan from c order by pr_id, r"
    ).fetchall():
        by_pr[pid].append(CommitFacts(sha, statuses.get(sha, {}), plan))
    yield from by_pr.items()


def comment_heads(con: duckdb.DuckDBPyConnection) -> dict[int, list[tuple[str, str]]]:
    """(commit_id, original_commit_id) of every inline comment, by PR."""
    found: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for pid, head, original in con.execute(
        """select v.pr_id, rc.commit_id, rc.original_commit_id from pr_review_comments rc
           join pr_reviews v on v.id = rc.pull_request_review_id"""
    ).fetchall():
        found[pid].append((head, original))
    return found


def root_comments(con: duckdb.DuckDBPyConnection, unreadable: list[int]) -> dict[int, list]:
    """Thread-opening inline comments with a hunk, by PR; unparseable hunks go to `unreadable`."""
    found: dict[int, list[RawComment]] = defaultdict(list)
    rows = con.execute(
        """select distinct on (rc.id) v.pr_id, rc.id, rc.original_commit_id, rc.path,
             rc.diff_hunk, rc.body, rc.user_type = 'User' and rc.user not like '%[bot]'
           from pr_review_comments rc join pr_reviews v on v.id = rc.pull_request_review_id
           where rc.in_reply_to_id is null and rc.diff_hunk is not null
           order by rc.id"""
    ).fetchall()
    for pid, cid, sha, path, hunk, body, human in rows:
        try:
            line = anchor_line(hunk)
        except PatchError:
            unreadable.append(cid)
            continue
        found[pid].append(RawComment(Comment(cid, sha, path, line, bool(human)), body or "", hunk))
    return found


def pr_commits(
    con: duckdb.DuckDBPyConnection, pr_ids: set[int], unreadable: list[str]
) -> Iterator[tuple[int, list[Commit], dict[tuple[int, str], str]]]:
    """For each PR in `pr_ids`: commits in row order, and the raw patches by (index, file)."""
    con.execute("create or replace temp table scope (pr_id bigint)")
    con.executemany("insert into scope values (?)", [(pid,) for pid in sorted(pr_ids)])
    cursor = con.execute(
        """select c.pr_id, c.sha, d.filename, d.status, d.patch from c join scope using (pr_id)
           left join pr_commit_details d on d.sha = c.sha and d.pr_id = c.pr_id
           order by c.pr_id, c.r"""
    )
    current: int | None = None
    rows: list[tuple] = []
    while batch := cursor.fetchmany(FETCH_ROWS):
        for row in batch:
            if row[0] != current and rows:
                yield _assemble(rows, unreadable)
                rows = []
            current = row[0]
            rows.append(row)
    if rows:
        yield _assemble(rows, unreadable)


def _assemble(rows: list[tuple], unreadable: list[str]) -> tuple[int, list[Commit], dict]:
    order: list[str] = []
    files: dict[str, dict[str, FileState] | None] = {}
    patches: dict[tuple[int, str], str] = {}
    for _, sha, name, status, patch in rows:
        if sha not in files:
            order.append(sha)
            files[sha] = None
        if name is None:
            continue
        files[sha] = files[sha] or {}
        files[sha][name] = FileState(status or "unknown", _hunks(patch, sha, unreadable))
        if patch:
            patches[(len(order) - 1, name)] = patch
    return rows[0][0], [Commit(sha, files[sha]) for sha in order], patches


def _hunks(patch: str | None, sha: str, unreadable: list[str]) -> tuple | None:
    if not patch:
        return None
    try:
        return tuple(parse_patch(patch))
    except PatchError:
        unreadable.append(sha)
        return None
