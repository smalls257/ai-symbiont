import json
from dataclasses import asdict, replace

import pytest

from record_builders import PUBLIC, edit, run, session, user
from symbiont.core.counters import Counters
from symbiont.core.similarity import Similarity
from symbiont.records.schema import Provenance, dump_jsonl, load_jsonl
from symbiont.service.app import (
    NOTHING_MATCHES,
    SPARK_WITHHELD,
    Service,
    ServiceMode,
    ServiceParts,
)
from symbiont.service.events import EventLog
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, remine

pytestmark = pytest.mark.periphery

PROJECT = "tobymao/sqlglot"
PRIVATE = Provenance(dataset="SWE-chat", license="ODC-BY", spark_safe=False)
COMMAND = "pytest tests/test_parser.py"


def failing_session(session_id, provenance=PUBLIC):
    records = session(user("fix it"), run(COMMAND, 1, "AssertionError"), edit("sqlglot/parser.py"))
    return [replace(r, session_id=session_id, provenance=provenance) for r in records]


# Synthetic logs are written as records JSONL and read back by this test reader,
# standing in for a harness reader.
READER = "records-jsonl"


def read_records_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


READERS = {READER: read_records_jsonl}


def write_log(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        dump_jsonl(records, fh)
    return path


def make_store(tmp_path, *sessions):
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = Store.open(tmp_path / "store.db")
    logs = [write_log(tmp_path / f"log{i}.jsonl", s) for i, s in enumerate(sessions)]
    sources = [Source(PROJECT, READER, str(log)) for log in logs]
    remine(store, PROJECT, MiningRules(READERS, frozenset()), adding=sources)
    return store


def make_service(
    tmp_path, store, mode=ServiceMode.WARN_AND_RECALL, decider=None, held_out=(), readers=READERS
):
    events = EventLog(tmp_path / "run", "counters")
    parts = ServiceParts(store, decider or Counters(), events, mode, frozenset(held_out), readers)
    return Service(parts), events


def learn_body(log, project=PROJECT):
    return {"reader": READER, "session_log_path": str(log), "project": project}


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
    log = write_log(tmp_path / "session.jsonl", failing_session("new"))
    spy = StateSpy()
    service, events = make_service(tmp_path, make_store(tmp_path), decider=spy)
    service.respond("/observe", observe_body())
    learned = service.respond("/learn", learn_body(log))
    assert learned.status == 200 and learned.body["learned_steps"] == 3
    service.respond("/observe", observe_body("second"))
    assert spy.seen[0] == frozenset() and len(spy.seen[-1]) == 1
    assert events_of(events)[-2]["hook"] == "learn"


def test_learn_refuses_a_missing_log_an_unknown_reader_and_extra_fields(tmp_path):
    service, _ = make_service(tmp_path, make_store(tmp_path))
    assert service.respond("/learn", learn_body(tmp_path / "gone")).status == 400
    unknown = learn_body(tmp_path / "gone") | {"reader": "no-such-harness"}
    assert "no-such-harness" in service.respond("/learn", unknown).body["error"]
    assert service.respond("/learn", learn_body("x") | {"mode": "fast"}).status == 400


def test_learn_refuses_a_held_out_task_and_registers_nothing(tmp_path):
    held = [replace(r, task_id="tobymao__sqlglot-4001") for r in failing_session("held")]
    log = write_log(tmp_path / "held.jsonl", held)
    store = make_store(tmp_path)
    service, _ = make_service(tmp_path, store, held_out={"tobymao/sqlglot#4001"})
    response = service.respond("/learn", learn_body(log))
    assert response.status == 409 and "held out" in response.body["error"]
    assert store.sources(PROJECT) == [] and store.lessons(PROJECT) == []


def test_learn_re_reads_every_registered_log_and_keeps_only_lessons(tmp_path):
    store = make_store(tmp_path, failing_session("a"))
    service, _ = make_service(tmp_path, store)
    log = write_log(tmp_path / "b.jsonl", failing_session("b"))
    assert service.respond("/learn", learn_body(log)).status == 200
    assert [p.session_id for p in store.pain_points(PROJECT)] == ["a", "b"]
    assert len(store.sources(PROJECT)) == 2


def test_spark_bound_observe_never_pushes_private_record(tmp_path):
    store = make_store(tmp_path, failing_session("p1", PRIVATE), failing_session("p2", PRIVATE))
    service, events = make_service(tmp_path, store)
    response = service.respond("/observe", observe_body() | {"spark_bound": True})
    assert response.status == 409 and SPARK_WITHHELD in response.body["error"]
    assert COMMAND not in json.dumps(response.body)
    (event,) = events_of(events)
    assert event["status"] == 409 and event["route"] == "observe"
    local = service.respond("/observe", observe_body("again"))
    assert local.status == 200 and local.body["notes"]


@pytest.mark.parametrize("route", ["/observe", "/recall"])
@pytest.mark.parametrize("value", ["true", 1, "yes", None])
def test_spark_bound_must_be_a_real_boolean(tmp_path, route, value):
    store = make_store(tmp_path, failing_session("p1", PRIVATE), failing_session("p2", PRIVATE))
    service, events = make_service(tmp_path, store)
    ask = {"question": "test_parser", "project": PROJECT} if route == "/recall" else observe_body()
    response = service.respond(route, ask | {"spark_bound": value})
    assert response.status == 400 and "spark_bound" in response.body["error"]
    assert COMMAND not in json.dumps(response.body)
    assert events_of(events)[-1]["status"] == 400


def test_spark_bound_observe_withholds_a_warning_learned_from_another_project(tmp_path):
    other = [replace(r, project="priv/repo") for r in failing_session("p1", PRIVATE)]
    other += [replace(r, project="priv/repo") for r in failing_session("p2", PRIVATE)]
    log = write_log(tmp_path / "private.jsonl", other)
    service, events = make_service(tmp_path, make_store(tmp_path))
    assert service.respond("/learn", learn_body(log, "priv/repo")).status == 200
    local = service.respond("/observe", observe_body())
    assert local.status == 200 and local.body["notes"], "the learned warning reaches a local caller"
    spark = service.respond("/observe", observe_body("again") | {"spark_bound": True})
    assert spark.status == 409 and SPARK_WITHHELD in spark.body["error"]
    assert COMMAND not in json.dumps(spark.body)


def test_observe_recalls_no_raw_records_because_none_are_stored(tmp_path):
    store = two_failures(tmp_path)
    service, events = make_service(tmp_path, store, ServiceMode.RECALL_ONLY, decider=Similarity())
    response = service.respond("/observe", observe_body())
    assert response.status == 200 and response.body["notes"] == []
    assert events_of(events)[-1]["recalled"] == 0


def test_a_warning_says_how_it_was_resolved_and_what_to_check(tmp_path):
    fixed = session(
        run(COMMAND, 1, "AssertionError"), run("pip install pyyaml"), run(COMMAND, 0, "ok")
    )
    service, _ = make_service(tmp_path, make_store(tmp_path, fixed, failing_session("b")))
    (note,) = service.respond("/observe", observe_body()).body["notes"]
    assert "pip install pyyaml" in note and f"Check: run `{COMMAND}`" in note


def test_recall_answers_with_structured_lessons(tmp_path):
    service, _ = make_service(tmp_path, two_failures(tmp_path))
    answer = service.respond("/recall", {"question": "test_parser", "project": PROJECT}).body
    assert answer["answer"].startswith("What happened: ") and "Check: " in answer["answer"]
    assert answer["records"] == [["a", 1], ["b", 1]]


def test_spark_bound_observe_recalls_through_the_guarded_view(tmp_path):
    clean = make_store(tmp_path / "c", failing_session("a"), failing_session("b"))
    service, _ = make_service(tmp_path / "c", clean, ServiceMode.RECALL_ONLY, decider=Similarity())
    ok = service.respond("/observe", observe_body() | {"spark_bound": True})
    assert ok.status == 200
    mixed = make_store(tmp_path / "m", failing_session("a"), failing_session("p", PRIVATE))
    guarded, _ = make_service(tmp_path / "m", mixed, ServiceMode.RECALL_ONLY, decider=Similarity())
    refused = guarded.respond("/observe", observe_body() | {"spark_bound": True})
    assert refused.status == 409


def test_recall_answer_repeats_no_sentence(tmp_path):
    service, _ = make_service(tmp_path, two_failures(tmp_path))
    answer = service.respond("/recall", {"question": "test_parser", "project": PROJECT}).body[
        "answer"
    ]
    sentences = [s for s in answer.split(". ") if s]
    assert len(sentences) == len(set(sentences))


def test_an_unrecognised_task_id_is_refused_with_its_reason(tmp_path):
    odd = [replace(r, task_id="not a benchmark id") for r in failing_session("odd")]
    log = write_log(tmp_path / "odd.jsonl", odd)
    service, _ = make_service(tmp_path, make_store(tmp_path), held_out={"tobymao/sqlglot#1"})
    response = service.respond("/learn", learn_body(log))
    assert response.status == 422 and "not a benchmark id" in response.body["error"]


def test_learn_reads_the_new_log_once(tmp_path):
    reads = []

    def counting(path, project):
        reads.append(path.name)
        return read_records_jsonl(path, project)

    store = make_store(tmp_path, failing_session("a"))
    service, _ = make_service(tmp_path, store, readers={READER: counting})
    log = write_log(tmp_path / "new.jsonl", failing_session("new"))
    assert service.respond("/learn", learn_body(log)).status == 200
    assert reads.count("new.jsonl") == 1 and reads.count("log0.jsonl") == 1
