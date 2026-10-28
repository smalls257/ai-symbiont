"""Wires a Service from a data directory; the decider is whatever the caller passes."""

import time
from pathlib import Path

from symbiont.core.counters import Counters
from symbiont.core.slot import Decider
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.store.local import Store


def open_service(data_dir: Path, mode: ServiceMode, decider: Decider | None = None) -> Service:
    """A service over `data_dir/store.db`, logging to `data_dir/runs/<utc stamp>/events.jsonl`.

    Counters fill the slot until a selection result names a live learner.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    filler = decider or Counters()
    run_dir = data_dir / "runs" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    parts = ServiceParts(
        Store.open(data_dir / "store.db"), filler, EventLog(run_dir, filler.name), mode
    )
    return Service(parts)
