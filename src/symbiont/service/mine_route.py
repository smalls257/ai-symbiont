"""Mining past sessions as a service job: `/mine` starts it, others poll its progress.

The service owns the job (a CLI that mined into the store on its own would split the state); the
CLI and the dashboard are clients of the one progress answer. The job reads and mines without the
service lock and takes it only to save, so observe and recall stay answerable while it runs.
"""

import json
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from symbiont.miner.lessons import Lesson
from symbiont.service.dashboard_page import Page
from symbiont.service.events import Call
from symbiont.service.mining_jobs import (
    MiningJobs,
    MiningProgress,
    MiningState,
    MiningWork,
    NoMiningJobError,
)
from symbiont.service.request_shapes import (
    BadRequestError,
    checkout_of,
    mine_request_of,
    named_project,
)
from symbiont.store.checkouts import checkout_names, names_for
from symbiont.store.held_back import MiningOutcome, held_back_sentence, held_by_reason
from symbiont.store.local import Source
from symbiont.store.mining import MiningRules, mine_sources, with_ignored
from symbiont.store.repos import RepoStance

if TYPE_CHECKING:
    from symbiont.service.app import ServiceParts

NOT_ALLOWED = "run `symbiont repo allow` for this repository before mining it"
JSON_TYPE = "application/json"


class MineRoutes:
    """The routes that start a mining job and report how far it is."""

    def __init__(self, parts: "ServiceParts", jobs: MiningJobs, lock: threading.Lock) -> None:
        """`lock` is the one every service call holds; the job takes it only to save."""
        self._parts = parts
        self._jobs = jobs
        self._lock = lock

    def start(self, request: dict[str, Any], call: Call) -> dict[str, Any]:
        """Start mining the request's logs, or report the job already running.

        The caller holds the service lock. Raises BadRequestError for a bad request or a
        repository that was not allowed.
        """
        project, wanted = mine_request_of(request)
        registry = self._parts.gate.registry
        if registry is not None and registry.stance(project) is not RepoStance.GIVEN:
            raise BadRequestError(NOT_ALLOWED)
        known = self._parts.store.sources(project)
        new = [source for source in dict.fromkeys(wanted) if source not in known]
        every = [*known, *new]
        names = self._checkout_names(request, project)
        started = self._jobs.start(
            project, len(every), self._work(project, new, every, names), self._record_end(call)
        )
        if started:
            self._parts.events.append(call, None, [], [f"mining {len(every)} logs"])
        progress = self._jobs.progress(project)
        return {"started": started, **(progress.as_json() if progress else {})}

    def _checkout_names(self, request: dict[str, Any], project: str) -> frozenset[str]:
        """The directory names `project`'s checkouts go by; a named checkout is remembered."""
        registry = self._parts.gate.registry
        checkout = checkout_of(request)
        if checkout is None:
            return names_for(registry, project)
        if registry is not None:
            registry.record_checkout(project, checkout)
        return checkout_names(checkout)

    def progress(self, request: dict[str, Any]) -> dict[str, Any]:
        """The POST form of the progress answer, for clients that can only POST.

        Raises NoMiningJobError when no job ran for the project since the service started.
        """
        project = named_project(request)
        found = self._jobs.progress(project)
        if found is None:
            raise NoMiningJobError(_NO_JOB.format(project))
        return found.as_json()

    def progress_page(self, project: str) -> Page:
        """The GET form, for the dashboard: JSON, or 404 saying that no job ran."""
        found = self._jobs.progress(project)
        if found is None:
            return Page(404, JSON_TYPE, json.dumps({"error": _NO_JOB.format(project)}).encode())
        return Page(200, JSON_TYPE, json.dumps(found.as_json()).encode())

    def _work(
        self, project: str, new: list[Source], every: list[Source], names: frozenset[str]
    ) -> MiningWork:
        """The job body: mine every log, then save under the service lock."""
        setup = self._parts
        rules = with_ignored(mining_rules(setup, project, names), setup.store, project)

        def work(report: Callable[[list[Lesson]], None]) -> MiningOutcome:
            """Read and mine without the lock; store only when the whole run succeeded."""
            outcome = mine_sources(every, rules, report)
            with self._lock:
                setup.store.mined.save(project, new, outcome, held_out_tasks=setup.held_out_tasks)
            return outcome

        return work

    def _record_end(self, call: Call) -> Callable[[MiningProgress], None]:
        """A callback that logs how the job ended, so a failure is an event as well as a state."""

        def record(end: MiningProgress) -> None:
            """Append the event under the service lock."""
            with self._lock:
                if end.state is MiningState.FAILED:
                    self._parts.events.append_failure(call, 500, end.error or "mining failed")
                    return
                done = f"mined {end.sessions_total} logs into {end.lessons} lessons"
                if end.held_back:
                    done += "; " + held_back_sentence(held_by_reason(end.held_back))
                self._parts.events.append(call, None, [], [done])

        return record


def mining_rules(parts: "ServiceParts", project: str, names: frozenset[str]) -> MiningRules:
    """How `project` is mined now: the service's readers, hold-out and screening, its checkouts."""
    return MiningRules(
        parts.readers, parts.held_out_tasks, screen=parts.screen_rules(), repo_names=names
    )


_NO_JOB = "no mining has run for {} since the service started"


def progress_path(path: str) -> str | None:
    """The project in `/mining/<project>/progress`, or None for any other path."""
    parts = path.strip("/").split("/")
    named = len(parts) == 3 and parts[0] == "mining" and parts[2] == "progress"
    return parts[1] if named and parts[1] else None
