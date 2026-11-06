"""Ignore a whole pattern and bring it back: the dashboard's "Ignore this pattern" and Restore.

An ignored pattern does not vanish: it is listed here with its title, counted as held back on
every mining, and restored in one call. Every other reader sees it gone through `Store.lessons`
alone, so no route or hook repeats the filter.
"""

from collections.abc import Callable, Mapping
from typing import Any

from symbiont.core.notes import happened
from symbiont.miner.painpoint import Signal, Signature
from symbiont.service.context_route import context_target, save_context
from symbiont.service.request_shapes import BadRequestError, percent_decoded, require_keys
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

MAX_LABEL_CHARS = 90
Handler = Callable[[dict[str, Any]], dict[str, Any]]


def developer_routes(name: str, store: Store, registry: RepoRegistry | None) -> dict[str, Handler]:
    """The dashboard's own routes that apply to `name`: a lesson's words, ignore, restore."""
    found: Mapping[str, Handler] = {
        "ignored/restore": lambda request: restore_pattern(store, registry, request)
    }
    lesson, pattern = context_target(name), ignore_target(name)
    if lesson is not None:
        found = {name: lambda request: save_context(store, lesson, request)}
    if pattern is not None:
        found = {name: lambda request: ignore_pattern(store, registry, pattern, request)}
    return dict(found)


def ignore_target(route: str) -> str | None:
    """The lesson id of a `lessons/<id>/ignore` route, else None."""
    parts = route.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "lessons" and parts[2] == "ignore" and parts[1]:
        return percent_decoded(parts[1])
    return None


def ignore_pattern(
    store: Store, registry: RepoRegistry | None, lesson_id: str, request: dict[str, Any]
) -> dict[str, Any]:
    """Set aside every occurrence of the pattern `lesson_id` belongs to.

    Raises BadRequestError for a repository nobody allowed or a lesson id the project lacks.
    """
    project = _allowed_project(registry, request, frozenset({"project"}))
    found = store.catalog.find(lesson_id)
    if found is None or found[0] != project:
        raise BadRequestError(f"no pain point {lesson_id} in {project}")
    signature = found[1].pain_point.signature
    store.ignored.add(project, signature, happened(signature)[:MAX_LABEL_CHARS])
    return {"ignored": True, "signature": _signature_json(signature)}


def restore_pattern(
    store: Store, registry: RepoRegistry | None, request: dict[str, Any]
) -> dict[str, Any]:
    """Bring an ignored pattern back at once; its lessons were never deleted.

    Raises BadRequestError for a repository nobody allowed, a bad signature or a pattern that
    is not ignored.
    """
    project = _allowed_project(registry, request, frozenset({"project", "signal", "key"}))
    signature = _signature_of(request)
    if not store.ignored.remove(project, signature):
        raise BadRequestError(f"{signature.signal.value} {list(signature.key)} is not ignored")
    return {"restored": True, "signature": _signature_json(signature)}


def ignored_listing(store: Store, project: str) -> list[dict[str, Any]]:
    """The Ignored list: each pattern's label and signature, oldest first."""
    return [
        {"label": label, **_signature_json(signature)}
        for signature, label in store.ignored.listed(project)
    ]


def _signature_json(signature: Signature) -> dict[str, Any]:
    """The signature as the dashboard sends it back to restore."""
    return {"signal": signature.signal.value, "key": list(signature.key)}


def _signature_of(request: dict[str, Any]) -> Signature:
    """The signature a restore names, or BadRequestError."""
    key = request["key"]
    if not isinstance(key, list) or not all(isinstance(part, str) for part in key):
        raise BadRequestError("key must be a list of text")
    try:
        signal = Signal(request["signal"])
    except ValueError as exc:
        raise BadRequestError(f"unknown signal {request['signal']!r}") from exc
    return Signature(signal, tuple(key))


def _allowed_project(
    registry: RepoRegistry | None, request: dict[str, Any], fields: frozenset[str]
) -> str:
    """The request's project, when its fields are right and the developer allowed it."""
    require_keys(request, fields, frozenset(fields))
    project = request["project"]
    if not isinstance(project, str) or not project:
        raise BadRequestError("project must be text")
    if registry is not None and registry.stance(project) is not RepoStance.GIVEN:
        raise BadRequestError(f"run `symbiont repo allow` for {project} first")
    return project
