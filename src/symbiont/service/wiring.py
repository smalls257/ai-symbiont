"""Wires a Service from a data directory; the decider is whatever the caller passes."""

import json
import time
from pathlib import Path

from symbiont.core.counters import Counters
from symbiont.core.slot import Decider
from symbiont.core.warner import LogisticWarner, WarnerWeightsError, weights_from
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.memory_model import AdapterProvenance, MemoryModel
from symbiont.service.nightly import RecallJudges
from symbiont.store.consent import read_consent
from symbiont.store.local import Store

# Layout `scripts/routea/train_memory.py` writes: the adapter, one training manifest per run
# (ids and counts, written by `Store.forget_trained`), and the adapter's record (base model and
# provenance), written only after training succeeds.
ADAPTER_DIR = "adapter"
MANIFESTS_DIR = "manifests"
ADAPTER_RECORD = "adapter.json"


class MemorySetupError(ValueError):
    """The memory directory does not describe a trained adapter; the message names the path."""


def open_service(
    data_dir: Path,
    mode: ServiceMode,
    decider: Decider | None = None,
    memory: MemoryModel | None = None,
    judges: RecallJudges | None = None,
) -> Service:
    """A service over `data_dir/store.db`, logging to `data_dir/runs/<utc stamp>/events.jsonl`.

    Counters fill the slot until a selection result names a live learner.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    filler = decider or Counters()
    run_dir = data_dir / "runs" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    parts = ServiceParts(
        Store.open(data_dir / "store.db"),
        filler,
        EventLog(run_dir, filler.name),
        mode,
        memory=memory,
        judge=(judges or RecallJudges()).first_night,
        nightly=(judges or RecallJudges()).nightly,
        consent=read_consent(data_dir),
    )
    return Service(parts)


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
