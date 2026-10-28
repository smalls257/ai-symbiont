"""Wires a Service from a data directory; the decider is whatever the caller passes."""

import json
import time
from pathlib import Path

from symbiont.core.counters import Counters
from symbiont.core.slot import Decider
from symbiont.core.warner import LogisticWarner, WarnerWeightsError, weights_from
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.memory_model import MemoryModel
from symbiont.store.local import Store

# Layout `scripts/routea/train_memory.py` writes: the adapter, and one training manifest per
# project (ids and counts, written by `Store.forget_trained`).
ADAPTER_DIR = "adapter"
MANIFESTS_DIR = "manifests"


class MemorySetupError(ValueError):
    """The memory directory does not describe a trained adapter; the message names the path."""


def open_service(
    data_dir: Path,
    mode: ServiceMode,
    decider: Decider | None = None,
    memory: MemoryModel | None = None,
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
        project = json.loads(manifest.read_text(encoding="utf-8")).get("project")
        if not isinstance(project, str) or not project:
            raise MemorySetupError(f"{manifest} names no project")
        projects.add(project)
    return frozenset(projects)
