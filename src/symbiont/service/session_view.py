"""GET /dashboard/session: one session's strip, messages and failed commands, read on demand.

The log is read fresh and scrubbed here, then forgotten: nothing of it is stored.
The page is local and display is not egress, so dataset history is served like any other, scrubbed.
Only the log that holds the session is parsed: found by file name, else by a raw text check.
A sensor line carries sizes, never text.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from symbiont.miner.mine import sessions_of
from symbiont.miner.session_detail import session_detail
from symbiont.readers import Reader
from symbiont.readers.errors import ReadError
from symbiont.records.schema import Record
from symbiont.store.local import Source, Store
from symbiont.store.mining import UnknownReaderError, read_source
from symbiont.store.repos import RepoRegistry, RepoStance

NO_SESSION = "no such session"
UNREADABLE = "this session's log is no longer readable"
Sensor = Callable[[str, str], None]  # (project, line)
Answer = tuple[int, dict[str, Any]]


def session_answer(
    store: Store,
    registry: RepoRegistry | None,
    readers: Mapping[str, Reader],
    asked: Mapping[str, str],
    sensor: Sensor,
) -> Answer:
    """The status and JSON body for `?project=&id=`; 400 for a refused project, 404 for a miss."""
    project, ident = asked.get("project", ""), asked.get("id", "")
    refusal = _project_refusal(store, registry, project)
    if refusal:
        return 400, {"error": refusal}
    if ident not in {fact.session_id for fact in store.mined.session_facts(project)}:
        return 404, {"error": NO_SESSION}
    records, unreadable = _records_of(store, readers, project, ident)
    if not records:
        return 404, {"error": UNREADABLE if unreadable else NO_SESSION}
    body = _body(store, project, ident, records)
    sensor(
        project,
        f"session view: {len(records)} records, {body['total']} steps, {body['shown']} shown",
    )
    return 200, body


def _project_refusal(store: Store, registry: RepoRegistry | None, project: str) -> str:
    if not project or not store.sources(project):
        return f"unknown project {project!r}; choose one with ?project=NAME"
    if registry is not None and registry.stance(project) is not RepoStance.GIVEN:
        return f"run `symbiont repo allow` for {project} first"
    return ""


def _records_of(
    store: Store, readers: Mapping[str, Reader], project: str, ident: str
) -> tuple[list[Record], bool]:
    """The session's records from the log that holds it, and whether a log was unreadable."""
    holders, unreadable = _holders(store.sources(project), ident)
    for source in holders:
        found = _read(source, readers)
        if found is None:
            unreadable = True
            continue
        session = next((s for s in sessions_of(found) if s[0].session_id == ident), None)
        if session:
            return session, unreadable
    return [], unreadable


def _holders(sources: list[Source], ident: str) -> tuple[list[Source], bool]:
    """The sources that may hold `ident`, without parsing any: named by it, else mentioning it."""
    named = [s for s in sources if Path(s.path).stem == ident]
    if named:
        return named, False
    holders, unreadable = [], False
    for source in sources:
        try:
            mentions = _mentions(Path(source.path), ident.encode())
        except OSError:
            mentions = None  # reported through `unreadable`: the page says the log is gone
        if mentions is None:
            unreadable = True
        elif mentions:
            holders.append(source)
    return holders, unreadable


def _mentions(path: Path, needle: bytes) -> bool:
    """Whether the raw file contains `needle`; a folder may. OSError if unreadable."""
    if path.is_dir():
        return True
    with path.open("rb") as fh:
        return any(needle in line for line in fh)


def _read(source: Source, readers: Mapping[str, Reader]) -> list[Record] | None:
    try:
        return read_source(source, readers)
    except (OSError, ReadError, UnknownReaderError):
        return None


def _body(store: Store, project: str, ident: str, records: list[Record]) -> dict[str, Any]:
    body = session_detail(records).as_json()
    summary = next((s for s in store.review.summaries.all(project) if s.session_id == ident), None)
    body["outcome"] = summary.outcome.value if summary else None
    body["friction"] = summary.friction if summary else None
    if summary and summary.goal:
        body["goal"] = summary.goal
    return body
