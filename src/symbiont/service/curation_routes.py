"""The routes the session's model calls to curate a repository's lessons, through MCP tools.

symbiont makes no model calls itself: it offers candidates, and the model that is already running
the session judges them and saves its verdicts. Nothing is stored for a repository the developer
has not allowed, and history is shown only to a session of the same harness (see store.settings).
"""

import hashlib
from collections.abc import Callable
from typing import Any

from symbiont.core.correction_candidates import CAP, correction_candidates
from symbiont.core.failure_signature import failure_detail
from symbiont.core.notes import happened, resolution_clause
from symbiont.miner.lesson_context import (
    AuthoredLesson,
    LessonKind,
    Review,
    Severity,
    Verdict,
)
from symbiont.miner.secrets import scrub
from symbiont.miner.trained import lesson_id
from symbiont.service.request_shapes import BadRequestError, parse_applies, require_keys
from symbiont.store.local import Store
from symbiont.store.mining import read_source
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import HARNESSES, CorrectionSettings

BATCH = 40
REVIEW_BATCH = 20
MAX_ITEMS = 100
READER_HARNESS = {"claude-code": "claude_code", "muse-code": "muse_code"}
MAX_TEXT = 600


class CurationRoutes:
    """Candidate batches out, judgments in; each method is one route."""

    def __init__(
        self,
        store: Store,
        registry: RepoRegistry | None,
        settings: Callable[[], CorrectionSettings],
        readers: dict[str, Any],
    ) -> None:
        """Work on `store`; `registry` gates by the answer; `settings` is read on each call."""
        self._store = store
        self._registry = registry
        self._settings = settings
        self._readers = readers

    def routes(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        """The route names the service exposes, each taking a request and returning a body."""
        return {
            "lessons/add": self.add_lessons,
            "corrections/candidates": self.correction_candidates,
            "corrections/save": self.save_corrections,
            "reviews/candidates": self.review_candidates,
            "reviews/save": self.save_reviews,
            "focus": self.set_focus,
        }

    def add_lessons(self, request: dict[str, Any]) -> dict[str, Any]:
        """Store lessons the model wrote from what the developer pointed it to."""
        project = self._allowed_project(request, {"project", "lessons"})
        items = _items(request.get("lessons"), "lessons")
        added = [self._authored(project, item) for item in items]
        return {"added": len(added), "ids": added}

    def correction_candidates(self, request: dict[str, Any]) -> dict[str, Any]:
        """A batch of user turns that may be corrections, from histories this session may read."""
        project = self._allowed_project(request, {"project", "running_in"})
        running = request.get("running_in")
        if running not in HARNESSES:
            raise BadRequestError("running_in must be claude_code or muse_code")
        allowed, blocked = self._readable(project, running)
        decided = self._store.curation.decided(project)
        found = [
            c
            for c in correction_candidates(_records(allowed, self._readers))
            if c.candidate_id not in decided
        ]
        batch = found[-CAP:][:BATCH]
        return {
            "candidates": [
                {"candidate_id": c.candidate_id, "excerpt": scrub(c.excerpt), "after": c.after}
                for c in batch
            ],
            "remaining": max(0, len(found) - len(batch)),
            "not_shown": blocked,
        }

    def save_corrections(self, request: dict[str, Any]) -> dict[str, Any]:
        """Keep the model's judgments; each confirmed correction becomes a lesson."""
        project = self._allowed_project(request, {"project", "corrections"})
        items = _items(request.get("corrections"), "corrections")
        kept = 0
        for item in items:
            ident, rule = (
                _text(item, "candidate_id"),
                str(item.get("rule_in_plain_words", "")).strip(),
            )
            if item.get("is_correction") is True:
                if not rule:
                    raise BadRequestError(f"{ident} is a correction but has no rule_in_plain_words")
                lesson = AuthoredLesson(
                    _ident(rule), rule[:MAX_TEXT], LessonKind.CORRECTION, (), f"correction {ident}"
                )
                self._store.curation.add_authored(project, lesson)
                kept += 1
        self._store.curation.decide(project, [_text(item, "candidate_id") for item in items])
        return {"judged": len(items), "lessons_added": kept}

    def review_candidates(self, request: dict[str, Any]) -> dict[str, Any]:
        """A capped batch of mined pain points that have no verdict yet."""
        project = self._allowed_project(request, {"project"})
        reviewed = self._store.curation.reviews(project)
        waiting = [item for item in self._store.lessons(project) if lesson_id(item) not in reviewed]
        return {
            "candidates": [_candidate(item) for item in waiting[:REVIEW_BATCH]],
            "remaining": max(0, len(waiting) - REVIEW_BATCH),
        }

    def save_reviews(self, request: dict[str, Any]) -> dict[str, Any]:
        """Keep the model's verdicts; expected and noise silence a note, mistake adds its rule."""
        project = self._allowed_project(request, {"project", "reviews"})
        known = {lesson_id(item) for item in self._store.lessons(project)}
        items = _items(request.get("reviews"), "reviews")
        for item in items:
            ident = _text(item, "id")
            if ident not in known:
                raise BadRequestError(f"no pain point {ident} in {project}")
            self._store.curation.save_review(project, ident, _review(item))
        return {"reviewed": len(items)}

    def set_focus(self, request: dict[str, Any]) -> dict[str, Any]:
        """Remember what the developer said symbiont should pay attention to."""
        project = self._allowed_project(request, {"project", "text", "keywords", "sources"})
        focus = {
            "text": str(request.get("text", ""))[:MAX_TEXT],
            "keywords": _strings(request.get("keywords", []), "keywords"),
            "sources": _strings(request.get("sources", []), "sources"),
        }
        if self._registry is not None:
            self._registry.record_focus(project, focus)
        return {"saved": True}

    def _allowed_project(self, request: dict[str, Any], fields: set[str]) -> str:
        """The request's project, when its fields are right and the developer allowed it."""
        require_keys(request, frozenset(fields), frozenset({"project"}))
        project = request["project"]
        if not isinstance(project, str) or not project:
            raise BadRequestError("project must be text")
        if self._registry is not None and self._registry.stance(project) is not RepoStance.GIVEN:
            raise BadRequestError(f"run `symbiont repo allow` for {project} first")
        return project

    def _authored(self, project: str, item: dict[str, Any]) -> str:
        """Validate and store one written lesson; returns its id."""
        text = _text(item, "text_in_plain_words")[:MAX_TEXT]
        lesson = AuthoredLesson(
            _ident(text),
            text,
            _enum(LessonKind, item.get("kind"), "kind"),
            _strings(item.get("files", []), "files"),
            str(item.get("source_label", ""))[:80],
            _enum(Severity, item.get("severity", "medium"), "severity"),
            parse_applies(item.get("applies_to")),
        )
        self._store.curation.add_authored(project, lesson)
        return lesson.ident

    def _readable(self, project: str, running_in: str) -> tuple[list[Any], list[str]]:
        """The project's sources this session may read, and why the others are not shown."""
        settings, allowed, blocked = self._settings(), [], []
        for source in self._store.sources(project):
            history = READER_HARNESS.get(source.reader)
            if history is None:
                continue
            if settings.allows(history, running_in):
                allowed.append(source)
            elif history not in blocked:
                blocked.append(history)
        return allowed, [
            f"{name} history is not shown to a {running_in} session" for name in blocked
        ]


def _records(sources: list[Any], readers: dict[str, Any]) -> list[Any]:
    """Every record of the given sources, read fresh."""
    return [record for source in sources for record in read_source(source, readers)]


def _candidate(lesson: Any) -> dict[str, Any]:
    """One pain point as the model sees it for review: short, plain, no scores."""
    signature = lesson.pain_point.signature
    return {
        "id": lesson_id(lesson),
        "kind": signature.signal.value,
        "what_happened": happened(signature),
        "error": failure_detail(lesson.quote),
        "fix": resolution_clause(lesson) if lesson.resolution else None,
        "context": scrub(lesson.quote[:200]),
    }


def _review(item: dict[str, Any]) -> Review:
    """A verdict from a request item."""
    return Review(
        _enum(Verdict, item.get("verdict"), "verdict"),
        str(item.get("rule_in_plain_words", "")).strip()[:MAX_TEXT],
        str(item.get("title", "")).strip()[:120],
        item.get("merge_with") if isinstance(item.get("merge_with"), str) else None,
        parse_applies(item.get("applies_to")),
    )


def _items(value: Any, name: str) -> list[dict[str, Any]]:
    """A non-empty, capped list of objects."""
    ok = isinstance(value, list) and 0 < len(value) <= MAX_ITEMS
    if not ok or not all(isinstance(item, dict) for item in value):
        raise BadRequestError(f"{name} must be a list of 1 to {MAX_ITEMS} objects")
    return value


def _text(item: dict[str, Any], key: str) -> str:
    """A required non-empty string field."""
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadRequestError(f"{key} must be non-empty text")
    return value.strip()


def _strings(value: Any, name: str) -> tuple[str, ...]:
    """A list of strings as a tuple."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BadRequestError(f"{name} must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


def _enum(kind: Any, value: Any, name: str) -> Any:
    """A member of the enum `kind` by value, or BadRequestError naming the choices."""
    try:
        return kind(value)
    except ValueError as exc:
        choices = ", ".join(member.value for member in kind)
        raise BadRequestError(f"{name} must be one of: {choices}") from exc


def _ident(text: str) -> str:
    """A stable id for a written lesson from its words."""
    return "w-" + hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:12]
