"""GET /dashboard: the page, filled from the repository's store, and its two static files."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from symbiont.core.rule_relevance import situation_terms
from symbiont.miner.lessons import Lesson
from symbiont.miner.screen import ScreenRules
from symbiont.readers import Reader
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.effective_context import effective_contexts
from symbiont.service.ignore_route import ignored_listing
from symbiont.service.incident_view import incidents_snapshot
from symbiont.service.mining_jobs import MiningProgress, MiningState
from symbiont.service.request_shapes import percent_decoded
from symbiont.service.session_dates import session_dates_of
from symbiont.service.session_view import session_answer
from symbiont.service.stale_lessons import screened_now
from symbiont.service.topic_view import topic_snapshot
from symbiont.service.trend_view import trends_snapshot
from symbiont.service.triage_route import group_activity, triage_listing
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import DEFAULT_MIN_SESSIONS

STATIC = Path(__file__).parent / "static"
PLACEHOLDER = "__SYMBIONT_DATA__"
WATCHING_MINE = "mining"
JS = "text/javascript; charset=utf-8"
FILES = {
    "/dashboard/mining.js": ("mining.js", "text/javascript; charset=utf-8"),
    "/dashboard/struggle.js": ("struggle.js", "text/javascript; charset=utf-8"),
    "/dashboard/heldback.js": ("heldback.js", "text/javascript; charset=utf-8"),
    "/dashboard/painlist.js": ("painlist.js", "text/javascript; charset=utf-8"),
    "/dashboard/summary.js": ("summary.js", "text/javascript; charset=utf-8"),
    "/dashboard/ignored.js": ("ignored.js", "text/javascript; charset=utf-8"),
    "/dashboard/tip.js": ("tip.js", JS),
    "/dashboard/rename.js": ("rename.js", JS),
    "/dashboard/inbox_model.js": ("inbox_model.js", JS),
    "/dashboard/inbox_rows.js": ("inbox_rows.js", JS),
    "/dashboard/inbox_dialogs.js": ("inbox_dialogs.js", JS),
    "/dashboard/inbox.js": ("inbox.js", JS),
    "/dashboard/views.js": ("views.js", JS),
    "/dashboard/topics.js": ("topics.js", JS),
    "/dashboard/trends.js": ("trends.js", JS),
    "/dashboard/trends_side.js": ("trends_side.js", JS),
    "/dashboard/inbox.css": ("inbox.css", "text/css; charset=utf-8"),
    "/dashboard/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/dashboard/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}
NightlyOf = Callable[[str, Sequence[Lesson]], Mapping[str, object] | None]
HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
JSON = "application/json"


@dataclass(frozen=True)
class Live:
    """What the page reads that changes while the service runs: mining jobs and nightly state."""

    mining: Callable[[str], MiningProgress | None] = lambda project: None
    nightly: NightlyOf = lambda project, lessons: None
    # The developer's setting now; the page prefers the value the lessons were screened with.
    min_sessions: int = DEFAULT_MIN_SESSIONS
    # The logs the session page reads on demand, and where its one sensor line goes.
    readers: Mapping[str, Reader] = field(default_factory=dict)
    session_sensor: Callable[[str, str], None] = lambda project, line: None


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
        return _static_file(STATIC / name, content_type)
    if path.rstrip("/") == "/dashboard/session":
        return _session_page(store, registry, _query(query), live or Live())
    if path.rstrip("/") == "/ignored":
        return _ignored_page(store, registry, _query(query).get("project", ""))
    if path.rstrip("/") != "/dashboard":
        return Page(404, TEXT, f"no such page: {path}".encode())
    return _project_page(store, registry, query, today, live or Live())


def _static_file(file: Path, content_type: str) -> Page:
    """The asset, or a 404 naming it (a listed asset missing from the install is not a crash)."""
    if not file.is_file():
        return Page(404, TEXT, f"no such asset: {file.name}".encode())
    return Page(200, content_type, file.read_bytes())


def _ignored_page(store: Store, registry: RepoRegistry | None, project: str) -> Page:
    """GET /ignored?project=: the patterns set aside in `project`, as JSON (allowed repos only)."""
    if not project:
        return Page(400, TEXT, b"choose a repository with ?project=NAME")
    if registry is not None and registry.stance(project) is not RepoStance.GIVEN:
        return Page(400, TEXT, f"run `symbiont repo allow` for {project} first".encode())
    return Page(200, JSON, json.dumps({"ignored": ignored_listing(store, project)}).encode())


def _session_page(
    store: Store, registry: RepoRegistry | None, asked: dict[str, str], live: Live
) -> Page:
    """GET /dashboard/session?project=&id=: one session's detail as JSON."""
    status, body = session_answer(store, registry, live.readers, asked, live.session_sensor)
    return Page(status, JSON, json.dumps(body).encode())


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
    has_stage = bool(store.mined.session_facts(project))
    if progress is not None and (
        WATCHING_MINE in asked
        or _still_mining(progress, store.lessons(project), has_stage=has_stage)
    ):
        return Page(200, HTML, _mining_html(project, progress))
    focus = _focus_terms(registry, project)
    return Page(200, HTML, _html(store, project, today, focus, live))


def _still_mining(progress: MiningProgress, lessons: list[Lesson], *, has_stage: bool) -> bool:
    """Whether the Mine stage, not the pain-point view, is what the page must show.

    A finished job with no lesson still has session facts to show (where the agent struggled).
    """
    return progress.state is not MiningState.DONE or not (lessons or has_stage)


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


def _html(store: Store, project: str, today: date, focus: frozenset[str], live: Live) -> bytes:
    """The page with the repository's data injected where the contract says."""
    lessons = store.lessons(project)
    taught = screened_now(store, project, lessons, ScreenRules(live.min_sessions))
    ignored = ignored_listing(store, project)
    view = RepoView(
        project,
        lessons,
        effective_contexts(store, project),
        session_dates_of(store.mined.session_facts(project)),
        store.curation.reviews(project),
        store.curation.authored(project),
        focus,
        frozenset(store.contexts.all(project)) - frozenset(store.contexts.overrides(project)),
        live.nightly(project, taught),
        store.mined.counts(project),
        store.mined.struggle(project),
        store.mined.churn(project),
        store.mined.session_facts(project),
        store.mined.session_strips(project),
        min_sessions=store.mined.min_sessions_used(project) or live.min_sessions,
        ignored=len(ignored),
    )
    snapshot = dashboard_snapshot(view, today)
    snapshot["ignored"] = ignored
    snapshot["incidents"] = incidents_snapshot(store, project, ScreenRules(live.min_sessions))
    groups = snapshot["incidents"]["groups"] if snapshot["incidents"] else []
    session_days = list(session_dates_of(store.mined.session_facts(project)).values())
    seen = group_activity(store, project, groups, (today, session_days))
    snapshot["triage"] = triage_listing(store, project, today, seen)
    snapshot["topicView"] = topic_snapshot(store, project)
    snapshot["trends"] = trends_snapshot(store, project, snapshot["incidents"])
    return _page_filled_with(snapshot)


def _focus_terms(registry: RepoRegistry | None, project: str) -> frozenset[str]:
    """The terms the developer asked symbiont to pay attention to."""
    saved = registry.focus(project) if registry else None
    return situation_terms(" ".join(saved.get("keywords", []))) if saved else frozenset()
