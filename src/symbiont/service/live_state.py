"""What the dashboard reads that changes while the service runs, gathered in one place."""

from collections.abc import Mapping

from symbiont.readers import Reader
from symbiont.service.dashboard_page import Live
from symbiont.service.events import Call, EventLog, checked_nightly
from symbiont.service.mining_jobs import MiningJobs
from symbiont.service.repo_gate import RepoGate
from symbiont.store.settings import read_mining_settings


def live_state(
    gate: RepoGate, events: EventLog, readers: Mapping[str, Reader], jobs: MiningJobs
) -> Live:
    """Mining jobs, nightly state, the developer's setting and the session page's log readers."""
    data_dir = events.path.parent.parent

    def session_sensor(project: str, line: str) -> None:
        events.append(Call("dashboard/session", "", project), None, [], [line])

    return Live(
        jobs.progress,
        checked_nightly(gate.nightly_state, data_dir),
        read_mining_settings(data_dir).min_sessions,
        readers,
        session_sensor,
    )
