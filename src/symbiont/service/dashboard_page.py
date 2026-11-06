"""GET /dashboard: the page, filled from the repository's store, and its two static files."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from symbiont.core.rule_relevance import situation_terms
from symbiont.miner.lessons import Lesson
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.effective_context import effective_contexts
from symbiont.service.mining_jobs import MiningProgress, MiningState
from symbiont.service.request_shapes import percent_decoded
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry

STATIC = Path(__file__).parent / "static"
PLACEHOLDER = "__SYMBIONT_DATA__"
WATCHING_MINE = "mining"
FILES = {
    "/dashboard/mining.js": ("mining.js", "text/javascript; charset=utf-8"),
    "/dashboard/timeline.js": ("timeline.js", "text/javascript; charset=utf-8"),
    "/dashboard/treemap.js": ("treemap.js", "text/javascript; charset=utf-8"),
    "/dashboard/painlist.js": ("painlist.js", "text/javascript; charset=utf-8"),
    "/dashboard/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/dashboard/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}
NightlyOf = Callable[[str, Sequence[Lesson]], Mapping[str, object] | None]
HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"


@dataclass(frozen=True)
class Live:
    """What the page reads that changes while the service runs: mining jobs and nightly state."""

    mining: Callable[[str], MiningProgress | None] = lambda project: None
    nightly: NightlyOf = lambda project, lessons: None


@dataclass(frozen=True)
class Page:
    """What a transport sends for a GET."""

    status: int
    content_type: str
    body: bytes


def dashboard_page(
    store: Store,
    registry: RepoRegistry | None,
    target: str,
    today: date,
    live: Live | None = None,
) -> Page:
    """The response for a GET of `target` (a path with an optional query).

    The Mine stage alone shows while a job runs, failed or found nothing, and, for `?mining=1`
    (what `symbiont repo mine` opens), also after it finished, so a short job shows its result.
    """
    path, _, query = target.partition("?")
    if path in FILES:
        name, content_type = FILES[path]
        return Page(200, content_type, (STATIC / name).read_bytes())
    if path.rstrip("/") != "/dashboard":
        return Page(404, TEXT, f"no such page: {path}".encode())
    return _project_page(store, registry, query, today, live or Live())


def _project_page(
    store: Store, registry: RepoRegistry | None, query: str, today: date, live: Live
) -> Page:
    """The dashboard (or the Mine stage alone) for the project the query names or the only one."""
    asked = _query(query)
    chosen = asked.get("project")
    known = store.catalog.projects()
    project = chosen or (known[0] if len(known) == 1 else None)
    if project is None:
        listing = ", ".join(known) or "none yet; run `symbiont repo mine`"
        return Page(400, TEXT, f"choose a repository with ?project=NAME. Known: {listing}".encode())
    progress = live.mining(project)
    if progress is not None and (
        WATCHING_MINE in asked or _still_mining(progress, store.lessons(project))
    ):
        return Page(200, HTML, _mining_html(project, progress))
    focus = _focus_terms(registry, project)
    return Page(200, HTML, _html(store, project, today, focus, live.nightly))


def _still_mining(progress: MiningProgress, lessons: list[Lesson]) -> bool:
    """Whether the Mine stage, not the pain-point view, is what the page must show."""
    return progress.state is not MiningState.DONE or not lessons


def _mining_html(project: str, progress: MiningProgress) -> bytes:
    """The page with the mining job where the dashboard's data goes; mining.js takes over."""
    return _page_filled_with({"mining": {"project": project, "progress": progress.as_json()}})


def _page_filled_with(data: dict[str, Any]) -> bytes:
    """The page with `data` injected where the contract says (one JSON object, script-safe)."""
    safe = json.dumps(data).replace("</", "<\\/")
    page = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    return page.replace(PLACEHOLDER, safe).encode()


def _query(query: str) -> dict[str, str]:
    """The query string as a dict of decoded values."""
    pairs = (part.partition("=") for part in query.split("&") if part)
    return {percent_decoded(key): percent_decoded(value) for key, _, value in pairs}


def _html(
    store: Store, project: str, today: date, focus: frozenset[str], nightly: NightlyOf
) -> bytes:
    """The page with the repository's data injected where the contract says."""
    lessons = store.lessons(project)
    view = RepoView(
        project,
        lessons,
        effective_contexts(store, project),
        _session_dates(store, project),
        store.curation.reviews(project),
        store.curation.authored(project),
        focus,
        frozenset(store.contexts.all(project)) - frozenset(store.contexts.overrides(project)),
        nightly(project, lessons),
    )
    return _page_filled_with(dashboard_snapshot(view, today))


def _session_dates(store: Store, project: str) -> dict[str, date]:
    """Session id -> the day its log was last written, for the logs whose name is the id."""
    dates: dict[str, date] = {}
    for source in store.sources(project):
        log = Path(source.path)
        if log.is_file():
            when = date.fromtimestamp(log.stat().st_mtime)
            dates[log.stem] = dates[log.parent.name] = when
    return dates


def _focus_terms(registry: RepoRegistry | None, project: str) -> frozenset[str]:
    """The terms the developer asked symbiont to pay attention to."""
    saved = registry.focus(project) if registry else None
    return situation_terms(" ".join(saved.get("keywords", []))) if saved else frozenset()
