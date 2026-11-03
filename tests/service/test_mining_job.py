"""Mining as a tracked job: start, watch, finish or fail, and the dashboard that follows it.

Failures guarded against: a Black Box (a long mining run nobody can watch), a Silent Fallback (a
failed run that leaves an empty dashboard) and a Distributed Monolith (a client mining into the
store behind the service's back).
"""

import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from record_builders import edit, run, session
from symbiont.core.counters import Counters
from symbiont.readers.errors import ReadError
from symbiont.service.app import Service, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.repo_gate import RepoGate
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"
SOURCES = [["fake", "/logs/one.jsonl"], ["fake", "/logs/two.jsonl"]]


def troubled_session(path: Path, project: str):
    steps = session(
        run("pytest tests/test_parser.py", 1, IMPORT),
        edit("app/parser.py", diff="-a\n+def parse(text):\n"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    return [replace(step, project=project, session_id=path.stem) for step in steps]


class Reading:
    """A fake reader the test can hold open on its second log, to watch a running job."""

    def __init__(self):
        self.second_log_may_finish = threading.Event()
        self.second_log_reached = threading.Event()
        self.hold = False

    def __call__(self, path, project):
        if self.hold and path.stem == "two":
            self.second_log_reached.set()
            assert self.second_log_may_finish.wait(10)
        return troubled_session(path, project)


def failing_reader(path, project):
    raise ReadError(path, 3, "not a JSON line")


def service_with(tmp_path, reader, *, stance=RepoStance.GIVEN):
    registry = RepoRegistry(tmp_path)
    if stance is not None:
        registry.record_stance("demo", stance)
    parts = ServiceParts(
        Store.open(tmp_path / "store.db"),
        Counters(),
        EventLog(tmp_path / "runs", "counters"),
        readers={"fake": reader},
        gate=RepoGate(registry),
    )
    return Service(parts), parts


def start(service, project="demo", sources=SOURCES):
    return service.respond("/mine", {"project": project, "sources": sources})


def progress(service, project="demo"):
    page = service.page(f"/mining/{project}/progress")
    return page.status, json.loads(page.body)


def test_a_started_job_runs_to_done_and_the_lessons_are_stored(tmp_path):
    service, parts = service_with(tmp_path, Reading())

    started = start(service)
    service.wait_for_mining("demo", 30)

    assert started.status == 200 and started.body["started"] is True
    status, done = progress(service)
    assert status == 200 and done["state"] == "done" and done["error"] is None
    assert done["sessions_read"] == done["sessions_total"] == 2
    assert done["lessons"] >= 1 and done["fixes_paired"] >= 1 and done["pain_points"] >= 1
    assert all(len(title) <= 90 for title in done["recent"]) and done["recent"]
    assert len(parts.store.lessons("demo")) == done["lessons"]
    assert len(parts.store.sources("demo")) == 2


def test_progress_is_visible_while_the_job_is_still_reading(tmp_path):
    reading = Reading()
    reading.hold = True
    service, parts = service_with(tmp_path, reading)

    start(service)
    assert reading.second_log_reached.wait(10)

    status, running = progress(service)
    assert status == 200 and running["state"] == "running"
    assert (running["sessions_read"], running["sessions_total"]) == (1, 2)
    assert running["pain_points"] >= 1 and running["recent"]
    assert parts.store.lessons("demo") == [], "nothing is stored until the run succeeds"
    assert start(service).body["started"] is False, "a second start follows the running job"

    reading.second_log_may_finish.set()
    service.wait_for_mining("demo", 30)
    assert progress(service)[1]["state"] == "done"


def test_a_failed_job_keeps_its_reason_stores_nothing_and_is_an_event(tmp_path):
    service, parts = service_with(tmp_path, failing_reader)

    start(service)
    service.wait_for_mining("demo", 30)

    status, failed = progress(service)
    assert status == 200 and failed["state"] == "failed"
    assert "one.jsonl:3: not a JSON line" in failed["error"]
    assert parts.store.lessons("demo") == [] and parts.store.sources("demo") == []
    events = [
        json.loads(line) for line in parts.events.path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(e["route"] == "mine" and "not a JSON line" in e.get("reason", "") for e in events)


def test_the_dashboard_shows_the_job_while_it_runs_and_when_it_failed(tmp_path):
    reading = Reading()
    reading.hold = True
    service, _ = service_with(tmp_path, reading)
    start(service)
    assert reading.second_log_reached.wait(10)

    running = service.page("/dashboard?project=demo")
    assert running.status == 200
    assert b'"mining": {"project": "demo"' in running.body and b'"state": "running"' in running.body
    assert b"painPoints" not in running.body

    reading.second_log_may_finish.set()
    service.wait_for_mining("demo", 30)
    assert b"painPoints" in service.page("/dashboard?project=demo").body

    broken, _ = service_with(tmp_path / "broken", failing_reader)
    start(broken)
    broken.wait_for_mining("demo", 30)
    page = broken.page("/dashboard?project=demo")
    assert (
        page.status == 200 and b'"state": "failed"' in page.body and b"not a JSON line" in page.body
    )


def test_a_repository_nobody_allowed_is_not_mined(tmp_path):
    service, parts = service_with(tmp_path, Reading(), stance=None)

    refused = start(service)

    assert refused.status == 400 and "repo allow" in refused.body["error"]
    assert progress(service)[0] == 404
    assert parts.store.sources("demo") == []


def test_progress_of_a_project_that_never_mined_is_a_404_not_an_empty_answer(tmp_path):
    service, _ = service_with(tmp_path, Reading())

    status, body = progress(service, "nothing-here")
    posted = service.respond("/mine/progress", {"project": "nothing-here"})

    assert status == 404 and "no mining has run" in body["error"]
    assert posted.status == 404


@pytest.mark.parametrize(
    "request_body",
    [
        {"project": "demo", "sources": []},
        {"project": "demo", "sources": [["fake"]]},
        {"project": "demo", "sources": "x"},
        {"project": "demo"},
        {"project": "demo", "sources": SOURCES, "extra": 1},
    ],
)
def test_a_malformed_mine_request_is_a_400(tmp_path, request_body):
    service, _ = service_with(tmp_path, Reading())

    assert service.respond("/mine", request_body).status == 400


def test_the_progress_route_decodes_a_percent_encoded_project(tmp_path):
    service, _ = service_with(tmp_path, Reading())
    RepoRegistry(tmp_path).record_stance("my repo", RepoStance.GIVEN)

    start(service, project="my repo")
    service.wait_for_mining("my repo", 30)

    assert progress(service, "my%20repo")[1]["state"] == "done"


def test_a_done_job_with_stored_lessons_hands_the_page_to_the_pain_point_view(tmp_path):
    service, _ = service_with(tmp_path, Reading())
    start(service)
    service.wait_for_mining("demo", 30)

    page = service.page("/dashboard?project=demo")

    assert b"painPoints" in page.body and b'"mining"' not in page.body


def test_the_page_ships_the_mine_stage_script_before_the_dashboard_script(tmp_path):
    service, _ = service_with(tmp_path, Reading())

    script = service.page("/dashboard/mining.js")
    html = (service_dir() / "static" / "dashboard.html").read_text(encoding="utf-8")

    assert script.status == 200 and script.content_type.startswith("text/javascript")
    assert html.index("/dashboard/mining.js") < html.index("/dashboard/dashboard.js")


def service_dir():
    return Path(__file__).parents[2] / "src" / "symbiont" / "service"
