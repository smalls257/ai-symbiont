"""Read the review comments out of the output of a `gh` command.

Claude Code stores `gh api graphql ...reviewThreads...`, `gh api .../pulls/N/comments` and the
like as COMMAND records whose `raw` is the output. This finds the comments in it. Pure: no I/O.
Truncated or non-JSON output yields nothing, never a guess; the agent's own posts are skipped.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from symbiont.miner.commands import command_stages
from symbiont.miner.credential_patterns import scrub
from symbiont.miner.review_gist import (
    Severity,
    gist_of,
    reviewer_name,
    severity_of,
    without_people,
)
from symbiont.records.schema import Kind, Record

_FIELD_FLAGS = ("-f", "-F", "--field", "--raw-field")
_BODY_FLAGS = ("--body", "-b", "--body-file", "-F", "--input")
# `gh pr comment` and friends post what the agent typed; their output is never a review.
_POSTING_COMMANDS = {("pr", "comment"), ("pr", "review"), ("issue", "comment")}
NOT_DECODED = -1
CUT_OFF: tuple[Any, int] = (None, NOT_DECODED)
_REPLY_KEYS = ("in_reply_to_id", "in_reply_to", "replyTo")


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
    if not _may_show_comments(record):
        return ()
    found: dict[str, ReviewComment] = {}
    for document in _json_documents(record.raw):
        for node in _comment_nodes(document):
            comment = _comment_from(node)
            if comment is not None:
                found.setdefault(comment.comment_id, comment)
    return tuple(found.values())


def flagged_comment_text(fetch: Record, key: tuple[str, ...]) -> str:
    """`<reviewer> on <path>: <gist>` and the body of the fetched comment whose key is `key`.

    Raises LookupError when `fetch` shows no comment with that (path, reviewer, gist).
    """
    wanted = tuple(key[:3])
    for comment in review_comments_in(fetch):
        if (comment.path, comment.reviewer, comment.gist) == wanted:
            return f"{comment.reviewer} on {comment.path}: {comment.gist}\n{comment.body}"
    raise LookupError(f"{fetch.session_id}:{fetch.step} shows no review comment on {key[0]}")


def _may_show_comments(record: Record) -> bool:
    """A successful, read-only `gh` command; the substring checks skip tokenizing the rest."""
    command = record.command or ""
    if record.kind != Kind.COMMAND or record.exit_code not in (0, None):
        return False
    if '"body"' not in record.raw or "gh" not in command:
        return False
    return _runs_gh(command) and not _writes(command)


def _runs_gh(command: str) -> bool:
    return any(stage.program == "gh" for stage in command_stages(command))


def _writes(command: str) -> bool:
    """True when a `gh` stage posts, sends a body, uses a non-GET method or runs a mutation."""
    return any(_stage_writes(s.args) for s in command_stages(command) if s.program == "gh")


def _stage_writes(args: tuple[str, ...]) -> bool:
    fields = list(_field_values(args))
    if tuple(args[:2]) in _POSTING_COMMANDS or _method(args) not in ("", "GET"):
        return True
    if any(arg.split("=", 1)[0] in _BODY_FLAGS for arg in args if arg.startswith("-")):
        return True
    if any(field.startswith(("body=", "body@")) for field in fields):
        return True
    return any(_is_mutation(field) for field in fields)


def _field_values(args: tuple[str, ...]) -> Iterator[str]:
    """The value of every -f/-F/--field/--raw-field, spaced, attached or `=`-joined."""
    for index, arg in enumerate(args):
        if arg in _FIELD_FLAGS:
            yield args[index + 1] if index + 1 < len(args) else ""
        elif arg.startswith(("--field=", "--raw-field=")):
            yield arg.split("=", 1)[1]
        elif arg[:2] in ("-f", "-F") and len(arg) > 2 and arg[1] != "-":
            yield arg[2:]


def _method(args: tuple[str, ...]) -> str:
    """The upper-cased -X/--method value, "" when none is given."""
    for index, arg in enumerate(args):
        if arg in ("-X", "--method"):
            return args[index + 1].upper() if index + 1 < len(args) else ""
        if arg.startswith("--method="):
            return arg.split("=", 1)[1].upper()
        if arg.startswith("-X") and len(arg) > 2:
            return arg[2:].upper()
    return ""


def _is_mutation(field: str) -> bool:
    return field.startswith("query=") and field[6:].lstrip().lower().startswith("mutation")


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
            yield from _comment_nodes(_opening_comment(value, thread["nodes"]))
            return
        for child in value.values():
            yield from _comment_nodes(child)


def _opening_comment(thread: dict[str, Any], nodes: list[Any]) -> list[Any]:
    """The thread's first comment; none when it was resolved or outdated at the fetch."""
    return [] if thread.get("isResolved") or thread.get("isOutdated") else nodes[:1]


def _is_stale(node: dict[str, Any]) -> bool:
    """Outdated: GraphQL's `outdated`, or REST's null `position` with an `original_position`."""
    if node.get("outdated") is True:
        return True
    return "position" in node and node["position"] is None and bool(node.get("original_position"))


def _looks_like_comment(node: dict[str, Any]) -> bool:
    return isinstance(node.get("body"), str) and isinstance(node.get("path"), str)


def _login(node: dict[str, Any]) -> str | None:
    for key in ("author", "user"):
        actor = node.get(key)
        if isinstance(actor, str):
            return actor
        login = actor.get("login") if isinstance(actor, dict) else None
        if isinstance(login, str):
            return login
    return None


def _comment_from(node: dict[str, Any]) -> ReviewComment | None:
    login = _login(node)
    if login is None or _is_stale(node) or any(node.get(key) for key in _REPLY_KEYS):
        return None
    body = without_people(scrub(node["body"]))
    gist = gist_of(node["body"])
    if not gist:
        return None
    identity = node.get("id")
    comment_id = str(identity) if identity not in (None, "") else f"{node['path']}:{gist}"
    return ReviewComment(
        comment_id, reviewer_name(login), node["path"], gist, body, severity_of(node["body"])
    )
