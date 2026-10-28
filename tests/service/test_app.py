import json
from dataclasses import asdict, replace

import pytest

from record_builders import PUBLIC, edit, run, session, user
from symbiont.core.counters import Counters
from symbiont.records.schema import Provenance, dump_jsonl
from symbiont.service.app import (
    NOTHING_MATCHES,
    SPARK_WITHHELD,
    Service,
    ServiceMode,
    ServiceParts,
)
from symbiont.service.events import EventLog
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery

PROJECT = "tobymao/sqlglot"
PRIVATE = Provenance(dataset="SWE-chat", license="ODC-BY", spark_safe=False)
COMMAND = "pytest tests/test_parser.py"


def failing_session(session_id, provenance=PUBLIC):
    records = session(user("fix it"), run(COMMAND, 1, "AssertionError"), edit("sqlglot/parser.py"))
    return [replace(r, session_id=session_id, provenance=provenance) for r in records]


def make_store(tmp_path, *sessions):
    store = Store.open(tmp_path / "store.db")
    for records in sessions:
        store.add_records(records, held_out_tasks=frozenset())
    store.mine(PROJECT, references={})
    return store


def make_service(tmp_path, store, mode=ServiceMode.WARN_AND_RECALL, decider=None):
    events = EventLog(tmp_path / "run", "counters")
    parts = ServiceParts(store, decider or Counters(), events, mode)
    return Service(parts), events


def events_of(events):
    return [json.loads(line) for line in events.path.read_text().splitlines()]


def observe_body(session_id="live"):
    record = replace(run(COMMAND, None), session_id=session_id, step=0)
    return {
        "harness": "openhands",
        "session_id": session_id,
        "event": "pre_command",
        "payload": {"record": json.loads(json.dumps(asdict(record)))},
    }


def two_failures(tmp_path):
    return make_store(tmp_path, failing_session("a"), failing_session("b"))


def test_observe_returns_notes_and_logs_event(tmp_path):
    service, events = make_service(tmp_path, two_failures(tmp_path))
    response = service.respond("/observe", observe_body())
    assert response.status == 200 and len(response.body["notes"]) == 1
    assert "failed" in response.body["notes"][0] and COMMAND in response.body["notes"][0]
    (event,) = events_of(events)
    assert event["hook"] == "pre_command" and event["notes"] == response.body["notes"]
    assert event["trouble"][0] == "failed_command"


def test_recall_only_mode_observes_and_logs_but_never_warns(tmp_path):
    service, events = make_service(tmp_path, two_failures(tmp_path), ServiceMode.RECALL_ONLY)
    response = service.respond("/observe", observe_body())
    assert response.status == 200 and response.body["notes"] == []
    (event,) = events_of(events)
    assert event["trouble"][0] == "failed_command" and event["notes"] == []


def test_observe_rejects_a_payload_that_is_not_a_record(tmp_path):
    service, events = make_service(tmp_path, two_failures(tmp_path))
    body = observe_body() | {"payload": {"record": {"kind": "command"}}}
    assert service.respond("/observe", body).status == 400
    assert events_of(events)[0]["status"] == 400


def test_recall_plain_question_only(tmp_path):
    service, events = make_service(tmp_path, two_failures(tmp_path))
    extra = {"question": "what failed?", "project": PROJECT, "k": 5}
    response = service.respond("/recall", extra)
    assert response.status == 400 and "k" in response.body["error"]
    assert service.respond("/recall", {"project": PROJECT}).status == 400
    assert service.respond("/recall", ["not", "an", "object"]).status == 400
    assert [e["status"] for e in events_of(events)] == [400, 400, 400]


def test_recall_empty_store_says_no_history(tmp_path):
    service, _ = make_service(tmp_path, make_store(tmp_path))
    response = service.respond("/recall", {"question": "what failed?", "project": PROJECT})
    assert response.status == 200
    assert response.body == {"answer": "no history for this project yet", "records": []}


def test_recall_answers_from_history_and_says_when_nothing_matches(tmp_path):
    service, _ = make_service(tmp_path, two_failures(tmp_path))
    hit = service.respond("/recall", {"question": "how do I run test_parser?", "project": PROJECT})
    assert COMMAND in hit.body["answer"] and hit.body["records"]
    miss = service.respond("/recall", {"question": "zebra giraffe", "project": PROJECT})
    assert miss.body == {"answer": NOTHING_MATCHES, "records": []}


def test_spark_bound_recall_never_returns_private_record(tmp_path):
    store = make_store(tmp_path, failing_session("a"), failing_session("p", PRIVATE))
    service, events = make_service(tmp_path, store)
    ask = {"question": "how do I run test_parser?", "project": PROJECT, "spark_bound": True}
    response = service.respond("/recall", ask)
    assert response.status == 409 and SPARK_WITHHELD in response.body["error"]
    assert COMMAND not in json.dumps(response.body)
    assert events_of(events)[-1]["status"] == 409
    local = service.respond("/recall", ask | {"spark_bound": False})
    assert local.status == 200 and local.body["records"]


def test_unknown_route_is_404(tmp_path):
    service, _ = make_service(tmp_path, make_store(tmp_path))
    assert service.respond("/nope", {}).status == 404


class StateSpy(Counters):
    def __init__(self):
        super().__init__()
        self.seen = []

    def decide(self, x, situation, state):
        self.seen.append(state)
        return super().decide(x, situation, state)


def test_learn_updates_state_between_sessions(tmp_path):
    log = tmp_path / "session.jsonl"
    with log.open("w") as fh:
        dump_jsonl(failing_session("new"), fh)
    spy = StateSpy()
    service, events = make_service(tmp_path, make_store(tmp_path), decider=spy)
    service.respond("/observe", observe_body())
    learned = service.respond("/learn", {"session_log_path": str(log)})
    assert learned.status == 200 and learned.body["learned_steps"] == 3
    service.respond("/observe", observe_body("second"))
    assert spy.seen[0] == frozenset() and len(spy.seen[-1]) == 1
    assert events_of(events)[-2]["hook"] == "learn"


def test_learn_refuses_a_missing_log_and_a_held_out_task(tmp_path):
    service, _ = make_service(tmp_path, make_store(tmp_path))
    assert service.respond("/learn", {"session_log_path": str(tmp_path / "gone")}).status == 400
    assert service.respond("/learn", {"session_log_path": "x", "mode": "fast"}).status == 400


def test_spark_bound_observe_never_pushes_private_record(tmp_path):
    store = make_store(tmp_path, failing_session("p1", PRIVATE), failing_session("p2", PRIVATE))
    service, events = make_service(tmp_path, store)
    response = service.respond("/observe", observe_body() | {"spark_bound": True})
    assert response.status == 409 and SPARK_WITHHELD in response.body["error"]
    assert COMMAND not in json.dumps(response.body)
    (event,) = events_of(events)
    assert event["status"] == 409 and event["hook"] == "observe"
    local = service.respond("/observe", observe_body("again"))
    assert local.status == 200 and local.body["notes"]
