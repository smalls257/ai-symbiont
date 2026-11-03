"""Wires a Service from a data directory; the decider is whatever the caller passes."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from symbiont.core.counters import Counters
from symbiont.core.slot import Decider
from symbiont.core.warner import LogisticWarner, WarnerWeightsError, weights_from
from symbiont.miner.trained import lesson_id
from symbiont.readers import READERS
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.curation_routes import CurationRoutes
from symbiont.service.effective_context import effective_contexts
from symbiont.service.events import EventLog
from symbiont.service.lesson_list import REFLECTION, source_of
from symbiont.service.memory_model import AdapterProvenance, MemoryModel
from symbiont.service.nightly import NightlyJudges, RecallJudges
from symbiont.service.onboarding import Lookups
from symbiont.service.reflection import ReflectionDesk, ReflectionSensors
from symbiont.service.repo_gate import RepoGate
from symbiont.store.consent import read_consent
from symbiont.store.local import Store
from symbiont.store.reflections import ReflectionLedger
from symbiont.store.repos import RepoRegistry
from symbiont.store.settings import read_correction_settings

# Layout `scripts/routea/train_memory.py` writes: the adapter, one training manifest per run
# (ids and counts, written by `Store.forget_trained`), and the adapter's record (base model and
# provenance), written only after training succeeds.
ADAPTER_DIR = "adapter"
MANIFESTS_DIR = "manifests"
ADAPTER_RECORD = "adapter.json"


class MemorySetupError(ValueError):
    """The memory directory does not describe a trained adapter; the message names the path."""


@dataclass(frozen=True)
class Guards:
    """What stands between a decision and the agent: the recall judges and the repository answers.

    No `repos` means every repository is observed, which only tests and the demo service want.
    """

    judges: RecallJudges = field(default_factory=RecallJudges)
    repos: RepoRegistry | None = None
    # Where a repository's finished first night shows up, to tell the developer once. It is not
    # the recall judge: a repository with no record yet must keep the plain recall.
    nightly_news: NightlyJudges | None = None


def open_service(
    data_dir: Path,
    mode: ServiceMode,
    decider: Decider | None = None,
    memory: MemoryModel | None = None,
    guards: Guards | None = None,
) -> Service:
    """A service over `data_dir/store.db`, logging to `data_dir/runs/<utc stamp>/events.jsonl`.

    Counters fill the slot until a selection result names a live learner. With `guards.repos`, a
    repository that did not say yes is not observed (the plugin's per-repository consent).
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    guards = guards or Guards()
    filler = decider or Counters()
    run_dir = data_dir / "runs" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    store = Store.open(data_dir / "store.db")
    gate = RepoGate(guards.repos, guards.nightly_news, _lookups(store))
    curation = CurationRoutes(
        store, guards.repos, lambda: read_correction_settings(data_dir), dict(READERS)
    )
    events = EventLog(run_dir, filler.name)
    desk = _reflection_desk(guards, data_dir, gate, store, events)
    curation.also_serving("reflect", desk.ask)
    curation.also_serving("reflect/finished", desk.finished)
    parts = ServiceParts(
        store,
        filler,
        events,
        mode,
        memory=memory,
        judge=guards.judges.first_night,
        nightly=guards.judges.nightly,
        consent=read_consent(data_dir),
        curation=curation,
        gate=gate,
        reflecting=desk.awaiting_answer,
    )
    return Service(parts)


def _reflection_desk(
    guards: Guards, data_dir: Path, gate: RepoGate, store: Store, events: EventLog
) -> ReflectionDesk:
    """The session-end reflection desk, logging to `events` and counting from `store`."""
    sensors = ReflectionSensors(events, _reflection_lessons(store))
    return ReflectionDesk(guards.repos, ReflectionLedger(data_dir), gate, sensors)


def _reflection_lessons(store: Store) -> Callable[[str], int]:
    """How many lessons a project holds that a session-end reflection wrote."""
    return lambda project: sum(
        1 for item in store.curation.authored(project) if source_of(item) == REFLECTION
    )


def _lookups(store: Store) -> Lookups:
    """What the gate reads from the store."""
    return Lookups(
        contexts=lambda project: effective_contexts(store, project),
        written=store.curation.authored,
        pending_reviews=lambda project: _pending_reviews(store, project),
        lesson_count=lambda project: len(store.lessons(project)),
    )


def _pending_reviews(store: Store, project: str) -> int:
    """Mined pain points the session's model has not judged yet."""
    reviewed = store.curation.reviews(project)
    return sum(1 for lesson in store.lessons(project) if lesson_id(lesson) not in reviewed)


def load_warner(path: Path) -> LogisticWarner:
    """The logistic warner from a weights file `scripts/routea/fit_warner.py` wrote.

    Raises OSError when the file cannot be read and WarnerWeightsError when it is not weights.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise WarnerWeightsError(f"{path} is not JSON: {exc}") from exc
    return LogisticWarner(weights_from(document))


def trained_projects(memory_dir: Path) -> frozenset[str]:
    """Projects whose lessons trained the adapter in `memory_dir`, from their manifests.

    Raises MemorySetupError when there is no adapter or no manifest: a memory model that
    learned nothing would answer from its base weights, which is a made-up note.
    """
    if not (memory_dir / ADAPTER_DIR / "adapters.safetensors").is_file():
        raise MemorySetupError(f"no trained adapter in {memory_dir / ADAPTER_DIR}")
    manifests = sorted((memory_dir / MANIFESTS_DIR).glob("*.json"))
    if not manifests:
        raise MemorySetupError(f"no training manifest in {memory_dir / MANIFESTS_DIR}")
    projects = set()
    for manifest in manifests:
        try:
            project = json.loads(manifest.read_text(encoding="utf-8")).get("project")
        except (ValueError, AttributeError) as exc:
            raise MemorySetupError(f"{manifest} is not a training manifest") from exc
        if not isinstance(project, str) or not project:
            raise MemorySetupError(f"{manifest} names no project")
        projects.add(project)
    return frozenset(projects)


def adapter_provenance(memory_dir: Path) -> AdapterProvenance:
    """What trained the adapter, from its record; raises MemorySetupError when unrecorded."""
    record = memory_dir / ADAPTER_RECORD
    try:
        value = json.loads(record.read_text(encoding="utf-8"))["provenance"]
        return AdapterProvenance(value)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MemorySetupError(f"{record} does not record the adapter's provenance") from exc


def open_memory(url: str, memory_dir: Path) -> MemoryModel:
    """The memory model at `url` with what `memory_dir` says it learned and from what.

    Raises MemorySetupError (no adapter, manifest or provenance) and EgressRefusedError
    (a URL that is not loopback), both before the service starts.
    """
    return MemoryModel(url, trained_projects(memory_dir), adapter_provenance(memory_dir))
