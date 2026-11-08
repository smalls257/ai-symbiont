"""Read the review comments out of the output of a `gh` command.

Claude Code stores `gh api graphql ...reviewThreads...`, `gh api .../pulls/N/comments` and the
like as COMMAND records whose `raw` is the output. This finds the comments in it. Pure: no I/O.
Truncated or non-JSON output yields nothing, never a guess; the agent's own posts are skipped.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from symbiont.miner.commands import command_stages
from symbiont.miner.credential_patterns import scrub
from symbiont.miner.review_gist import Severity, gist_of, reviewer_name, severity_of
from symbiont.records.schema import Kind, Record

_POSTS_A_BODY = re.compile(
    r"(?:--field|--raw-field|--input|-[fF])\s+(?:body=|-)|--method\s+POST|-X\s+POST"
)
NOT_DECODED = -1
CUT_OFF: tuple[Any, int] = (None, NOT_DECODED)
_REPLY_KEYS = ("in_reply_to_id", "in_reply_to")


@dataclass(frozen=True)
class ReviewComment:
    """One reviewer comment on a changed file; the reviewer is a product name or "a teammate"."""

    comment_id: str
    reviewer: str
    path: str
    gist: str
    body: str
    severity: Severity


def review_comments_in(record: Record) -> tuple[ReviewComment, ...]:
    """The review comments a `gh` command's output shows, replies and the agent's posts excluded."""
    command = record.command or ""
    if record.kind != Kind.COMMAND or record.exit_code not in (0, None):
        return ()
    if not _runs_gh(command) or _writes(command):
        return ()
    found: dict[str, ReviewComment] = {}
    for document in _json_documents(record.raw):
        for node in _comment_nodes(document):
            comment = _comment_from(node)
            if comment is not None:
                found.setdefault(comment.comment_id, comment)
    return tuple(found.values())


def _runs_gh(command: str) -> bool:
    return any(stage.program == "gh" for stage in command_stages(command))


def _writes(command: str) -> bool:
    """A post, a body field, a piped-in body or a GraphQL mutation: the agent's own words."""
    return bool(_POSTS_A_BODY.search(command)) or "mutation" in command


def _json_documents(raw: str) -> list[Any]:
    """Every complete JSON value that starts a line or follows another; a cut-off one is dropped."""
    documents: list[Any] = []
    position = 0
    while position < len(raw):
        value, end = _decode_at(raw, position) if raw[position] in "{[" else CUT_OFF
        if end != NOT_DECODED:
            documents.append(value)
            position = end
            continue
        newline = raw.find("\n", position)
        if newline < 0:
            break
        position = newline + 1
    return documents


def _decode_at(raw: str, position: int) -> tuple[Any, int]:
    """The JSON value at `position` and where it ends; CUT_OFF when it is truncated or not JSON."""
    try:
        return json.JSONDecoder().raw_decode(raw, position)
    except ValueError:
        # Output cut off mid-document is expected (tool output is truncated); the caller skips it.
        return CUT_OFF


def _comment_nodes(value: Any) -> Iterator[dict[str, Any]]:
    """Dicts that look like a comment; of a thread only its first comment, the rest are replies."""
    if isinstance(value, list):
        for item in value:
            yield from _comment_nodes(item)
    elif isinstance(value, dict):
        if _looks_like_comment(value):
            yield value
            return
        thread = value.get("comments")
        if isinstance(thread, dict) and isinstance(thread.get("nodes"), list):
            yield from _comment_nodes(thread["nodes"][:1])
            return
        for child in value.values():
            yield from _comment_nodes(child)


def _looks_like_comment(node: dict[str, Any]) -> bool:
    return isinstance(node.get("body"), str) and isinstance(node.get("path"), str)


def _login(node: dict[str, Any]) -> str | None:
    for key in ("author", "user"):
        actor = node.get(key)
        if isinstance(actor, str):
            return actor
        if isinstance(actor, dict) and isinstance(actor.get("login"), str):
            return actor["login"]
    return None


def _comment_from(node: dict[str, Any]) -> ReviewComment | None:
    login = _login(node)
    if login is None or any(node.get(key) for key in _REPLY_KEYS):
        return None
    body = scrub(node["body"])
    gist = gist_of(node["body"])
    if not gist:
        return None
    identity = node.get("id")
    comment_id = str(identity) if identity not in (None, "") else f"{node['path']}:{gist}"
    return ReviewComment(
        comment_id, reviewer_name(login), node["path"], gist, body, severity_of(node["body"])
    )
