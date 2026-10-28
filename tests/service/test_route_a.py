"""Route A in the service: the warner decides, option A rations, the memory model writes."""

import json
from dataclasses import asdict, replace

import numpy as np
import pytest

from record_builders import run
from symbiont.core.features import N_FEATURES
from symbiont.core.warner import LogisticWarner, WarnerWeights
from symbiont.service.app import HELD_BY_RULE, Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.memory_model import MemoryModel
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery

PROJECT = "demo"
LINE = "Happened: `pytest` failed -> Resolved: you ran `pip install -e .` -> Check: run `pytest`"


def always_risky():
    coef = np.zeros(N_FEATURES + 1)
    coef[0] = 5.0
    return LogisticWarner(WarnerWeights(np.zeros(N_FEATURES), np.ones(N_FEATURES), coef, 0.5))


def transport_replying(content, prompts):
    def transport(request, timeout_s):
        prompts.append(json.loads(request.data)["messages"][1]["content"])
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    return transport


def make(tmp_path, content=LINE, projects=frozenset({PROJECT}), mode=ServiceMode.WARN_AND_RECALL):
    prompts = []
    memory = MemoryModel("http://127.0.0.1:8090", projects, transport_replying(content, prompts))
    events = EventLog(tmp_path / "run", "logistic")
    store = Store.open(tmp_path / "store.db")
    parts = ServiceParts(store, always_risky(), events, mode, memory=memory)
    return Service(parts), events, prompts


def observe(service, command="pytest tests/test_cli.py", exit_code=1, session_id="live"):
    record = replace(run(command, exit_code, "ModuleNotFoundError: demo"), project=PROJECT)
    record = replace(record, session_id=session_id, step=0)
    body = {
        "harness": "claude_code",
        "session_id": session_id,
        "event": "PostToolUseFailure",
        "payload": {"record": json.loads(json.dumps(asdict(record)))},
    }
    return service.respond("/observe", body)


def events_of(events):
    return [json.loads(line) for line in events.path.read_text().splitlines()]


def test_a_risky_failed_command_gets_the_memory_models_line(tmp_path):
    service, events, prompts = make(tmp_path)
    response = observe(service)
    assert (response.status, response.body) == (200, {"notes": [LINE]})
    assert prompts == [
        "In demo, `pytest tests/test_cli.py` failed with ModuleNotFoundError. "
        "Write one line: what happened -> how it was resolved -> the check to run."
    ]
    (event,) = events_of(events)
    assert event["memory_model"]["prompt_chars"] == len(prompts[0])
    assert event["memory_model"]["note_chars"] == len(LINE) and event["memory_model"]["ms"] >= 0
    assert prompts[0] not in json.dumps(event)


def test_option_a_spends_two_notes_per_session_spaced_apart(tmp_path):
    service, events, prompts = make(tmp_path)
    spoken = [bool(observe(service).body["notes"]) for _ in range(14)]
    assert spoken == [True] + [False] * 5 + [True] + [False] * 7
    assert len(prompts) == 2
    assert sum(event.get("held") == HELD_BY_RULE for event in events_of(events)) == 12
    assert observe(service, session_id="another").body["notes"] == [LINE]


def test_a_routine_step_never_asks_the_memory_model(tmp_path):
    service, _, prompts = make(tmp_path)
    assert observe(service, "ls", 0).body == {"notes": []}
    assert prompts == []


def test_an_invalid_reply_is_a_503_offline_never_an_empty_note(tmp_path):
    service, events, _ = make(tmp_path, content="I am not sure.")
    response = observe(service)
    assert response.status == 503 and "memory model reply unusable" in response.body["error"]
    assert events_of(events)[0]["status"] == 503


def test_a_project_the_adapter_never_learned_gets_no_memory_note(tmp_path):
    service, _, prompts = make(tmp_path, projects=frozenset({"other"}))
    observe(service)
    assert prompts == []
    answer = service.respond("/recall", {"question": "what broke?", "project": PROJECT})
    assert answer.body["answer"] == "no history for this project yet"


def test_recall_answers_through_the_memory_model(tmp_path):
    service, events, prompts = make(tmp_path)
    question = "What went wrong last time with `pytest tests/test_cli.py`?"
    response = service.respond("/recall", {"question": question, "project": PROJECT})
    assert response.body == {"answer": LINE, "records": []}
    assert prompts[0].startswith(f"In demo, a question about earlier work: {question}")
    assert events_of(events)[0]["memory_model"]["note_chars"] == len(LINE)


def test_recall_only_mode_never_warns_through_the_memory_model(tmp_path):
    service, _, prompts = make(tmp_path, mode=ServiceMode.RECALL_ONLY)
    assert observe(service).body == {"notes": []}
    assert prompts == []
