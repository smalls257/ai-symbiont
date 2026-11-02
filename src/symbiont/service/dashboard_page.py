"""GET /dashboard: the page, filled from the repository's store, and its two static files."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from symbiont.core.rule_relevance import situation_terms
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.effective_context import effective_contexts
from symbiont.service.request_shapes import percent_decoded
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry

STATIC = Path(__file__).parent / "static"
PLACEHOLDER = "__SYMBIONT_DATA__"
FILES = {
    "/dashboard/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/dashboard/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}
HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"


@dataclass(frozen=True)
class Page:
    """What a transport sends for a GET."""

    status: int
    content_type: str
    body: bytes


def dashboard_page(store: Store, registry: RepoRegistry | None, target: str, today: date) -> Page:
    """The response for a GET of `target` (a path with an optional query)."""
    path, _, query = target.partition("?")
    if path in FILES:
        name, content_type = FILES[path]
        return Page(200, content_type, (STATIC / name).read_bytes())
    if path.rstrip("/") != "/dashboard":
        return Page(404, TEXT, f"no such page: {path}".encode())
    chosen = _query(query).get("project")
    known = store.catalog.projects()
    project = chosen or (known[0] if len(known) == 1 else None)
    if project is None:
        listing = ", ".join(known) or "none yet; run `symbiont repo mine`"
        return Page(400, TEXT, f"choose a repository with ?project=NAME. Known: {listing}".encode())
    return Page(200, HTML, _html(store, project, today, _focus_terms(registry, project)))


def _query(query: str) -> dict[str, str]:
    """The query string as a dict of decoded values."""
    pairs = (part.partition("=") for part in query.split("&") if part)
    return {percent_decoded(key): percent_decoded(value) for key, _, value in pairs}


def _html(store: Store, project: str, today: date, focus: frozenset[str]) -> bytes:
    """The page with the repository's data injected where the contract says."""
    view = RepoView(
        project,
        store.lessons(project),
        effective_contexts(store, project),
        _session_dates(store, project),
        store.curation.reviews(project),
        store.curation.authored(project),
        focus,
    )
    safe = json.dumps(dashboard_snapshot(view, today)).replace("</", "<\\/")
    page = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    return page.replace(PLACEHOLDER, safe).encode()


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
