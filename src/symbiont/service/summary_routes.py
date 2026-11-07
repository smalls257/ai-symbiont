"""Session summaries in batches, then named topics: the session's model does the judging.

One request per session would cost hundreds, so digests go out `SUMMARY_BATCH` at a time and
topics are named in one request over every summary (the dry run on 365 sessions took 11).
symbiont makes no model call. A bad write is refused with what to resend, as the curation
routes do, and readable history follows their harness setting.
"""

from collections.abc import Callable
from typing import Any

from symbiont.miner.mine import sessions_of
from symbiont.miner.session_digest import SessionDigest, digest_of, session_corrections
from symbiont.miner.session_summary import SessionSummary, SummaryError, summary_from
from symbiont.miner.themes import Codebase
from symbiont.miner.topics import TopicMapError, topic_map_from
from symbiont.readers.harnesses import harness_for_reader
from symbiont.records.schema import Record
from symbiont.service.curation_routes import BATCH, CurationRoutes, items_of, running_harness
from symbiont.service.request_shapes import BadRequestError
from symbiont.store.local import Store
from symbiont.store.mining import read_source

SUMMARY_BATCH = BATCH
# Fewer than this many summaries gives topics nothing to group (Task 8 of the failure-cards plan).
MIN_TOPIC_SESSIONS = 30
SUMMARY_RESEND = (
    "Expected per summary: session_id (from the candidates), goal (at most 12 words), outcome "
    "(done|partly|stuck|unclear), friction (at most 10 words, or empty), noise (true or false). "
    "Fix the field and resend the SAME summaries unchanged."
)
TOPICS_RESEND = (
    "Expected: topics [{name (2 to 4 words), description, session_ids}], frictions "
    "[{name (2 to 5 words), description, session_ids}], correction_groups [{name (2 to 5 "
    "words), description, refs [[session_id, step]]}]. Every session in the candidates must be "
    "in exactly one topic (an 'Other' topic is allowed). Fix it and resend the whole map."
)


class SummaryRoutes:
    """Digests out, summaries in; summaries out, topic map in. Each method is one route."""

    def __init__(self, curation: CurationRoutes, store: Store, readers: dict[str, Any]) -> None:
        """Share `curation`'s consent gate and readable-history rule; work on `store`."""
        self._curation = curation
        self._store = store
        self._readers = readers

    def routes(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        """The route names the service exposes, each taking a request and returning a body."""
        return {
            "summaries/candidates": self.session_candidates,
            "summaries/save": self.save_summaries,
            "topics/candidates": self.topic_candidates,
            "topics/save": self.save_topics,
        }

    def session_candidates(self, request: dict[str, Any]) -> dict[str, Any]:
        """Up to SUMMARY_BATCH digests of mined sessions without a summary, oldest first."""
        project = self._curation.allowed_project(request, {"project", "running_in"})
        sessions, blocked = self._sessions(project, running_harness(request))
        mined = {fact.session_id for fact in self._store.mined.session_facts(project)}
        done = self._store.summaries.summarized(project)
        codebase = Codebase(frozenset({project}))
        waiting = [
            digest_of(s, codebase)
            for s in sessions
            if s[0].session_id in mined and s[0].session_id not in done
        ]
        waiting.sort(key=lambda digest: (digest.date, digest.session_id))
        batch = waiting[:SUMMARY_BATCH]
        answer: dict[str, Any] = {
            "candidates": [_digest_json(digest) for digest in batch],
            "remaining": len(waiting) - len(batch),
            "not_shown": blocked + self._withheld_datasets(project),
        }
        unmined = sum(1 for s in sessions if s[0].session_id not in mined)
        if unmined:
            answer["not_mined"] = f"re-mine to include {unmined} sessions"
        return answer

    def save_summaries(self, request: dict[str, Any]) -> dict[str, Any]:
        """Keep the model's summaries; an unknown id or an over-long field refuses the call."""
        project = self._curation.allowed_project(request, {"project", "summaries"})
        items = items_of(request.get("summaries"), "summaries")
        try:
            summaries = [summary_from(item) for item in items]
            self._require_mined(project, summaries)
        except (SummaryError, BadRequestError) as error:
            raise BadRequestError(f"{error}. {SUMMARY_RESEND}") from error
        self._store.summaries.save(project, summaries)
        return {"saved": len(summaries)}

    def topic_candidates(self, request: dict[str, Any]) -> dict[str, Any]:
        """Every readable summary to group, with its corrections; or how many more are needed."""
        project = self._curation.allowed_project(request, {"project", "running_in"})
        sessions, blocked = self._sessions(project, running_harness(request))
        kept = [s for s in self._offered_summaries(project, sessions) if not s.noise]
        if len(kept) < MIN_TOPIC_SESSIONS:
            short = MIN_TOPIC_SESSIONS - len(kept)
            return {
                "candidates": [],
                "summaries_still_needed": short,
                "message": f"{short} more summarized sessions are needed to name topics.",
                "not_shown": blocked + self._withheld_datasets(project),
            }
        found = {s[0].session_id: session_corrections(s) for s in sessions}
        started = {
            fact.session_id: fact.started for fact in self._store.mined.session_facts(project)
        }
        return {
            "candidates": [_summary_json(s, started.get(s.session_id), found) for s in kept],
            "not_shown": blocked + self._withheld_datasets(project),
        }

    def save_topics(self, request: dict[str, Any]) -> dict[str, Any]:
        """Keep the topic map when every offered, non-noise session is in exactly one topic."""
        project = self._curation.allowed_project(
            request, {"project", "running_in", "topics", "frictions", "correction_groups"}
        )
        sessions, _ = self._sessions(project, running_harness(request))
        body = {
            key: value for key, value in request.items() if key not in {"project", "running_in"}
        }
        offered = {(s[0].session_id, step) for s in sessions for step, _ in session_corrections(s)}
        try:
            topic_map = topic_map_from(body, self._offered_summaries(project, sessions), offered)
        except TopicMapError as error:
            raise BadRequestError(f"{error}. {TOPICS_RESEND}") from error
        self._store.summaries.save_topics(project, topic_map)
        return {
            "topics": len(topic_map.topics),
            "frictions": len(topic_map.frictions),
            "correction_groups": len(topic_map.correction_groups),
        }

    def _sessions(self, project: str, running_in: str) -> tuple[list[list[Record]], list[str]]:
        """The sessions of the sources this session may read, and why the others are not shown."""
        allowed, blocked = self._curation.readable_sources(project, running_in)
        records = [r for source in allowed for r in read_source(source, self._readers)]
        return sessions_of(records), blocked

    def _offered_summaries(
        self, project: str, sessions: list[list[Record]]
    ) -> list[SessionSummary]:
        """The summaries of sessions this session may read; others never reach its model."""
        readable = {s[0].session_id for s in sessions}
        return [s for s in self._store.summaries.all(project) if s.session_id in readable]

    def _withheld_datasets(self, project: str) -> list[str]:
        """One line per dataset reader whose history is never shown, with its session count."""
        datasets: dict[str, list[Record]] = {}
        for source in self._store.sources(project):
            if harness_for_reader(source.reader) is None:
                datasets.setdefault(source.reader, []).extend(read_source(source, self._readers))
        return [
            f"{reader} dataset history is not shown to a session model "
            f"({len(sessions_of(records))} sessions)"
            for reader, records in datasets.items()
        ]

    def _require_mined(self, project: str, summaries: list[SessionSummary]) -> None:
        known = {fact.session_id for fact in self._store.mined.session_facts(project)}
        unknown = sorted({s.session_id for s in summaries} - known)
        if unknown:
            raise BadRequestError(f"no session {', '.join(unknown)} in {project}")


def _digest_json(digest: SessionDigest) -> dict[str, Any]:
    return {
        "session_id": digest.session_id,
        "date": digest.date,
        "title": digest.title,
        "asks": list(digest.asks),
        "files": list(digest.files),
        "failed": list(digest.failed),
        "corrections": list(digest.corrections),
        "last_turns": list(digest.last_turns),
    }


def _summary_json(
    summary: SessionSummary, started: str | None, corrections: dict[str, list[tuple[int, str]]]
) -> dict[str, Any]:
    return {
        "session_id": summary.session_id,
        "date": started or "date unknown",
        "goal": summary.goal,
        "outcome": summary.outcome.value,
        "friction": summary.friction,
        "corrections": [
            {"step": step, "text": text} for step, text in corrections.get(summary.session_id, [])
        ],
    }
