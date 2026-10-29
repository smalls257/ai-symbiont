"""The teacher model sends every agent turn through one capped Spark session (stubbed agent)."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from symbiont.egress.credentials import ApiKey
from symbiont.egress.spark import SparkSession
from symbiont.egress.spend import Ledger, SpendCapError, SpendCaps, Tier

CALIBRATION = Path(__file__).resolve().parents[2] / "scripts" / "calibration"
REPLY = {
    "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 2000, "completion_tokens": 100},
}


class FakeLitellmModel:
    abort_exceptions: list = []

    def __init__(self, **kwargs):
        self.config = kwargs


class FakeResponse:
    def __init__(self, **out):
        self.out = out

    def model_dump(self):
        return self.out


def load(monkeypatch):
    litellm_model = types.SimpleNamespace(LitellmModel=FakeLitellmModel)
    tools = types.SimpleNamespace(BASH_TOOL={"type": "function", "function": {"name": "bash"}})
    for name, stub in {
        "litellm": types.SimpleNamespace(ModelResponse=FakeResponse),
        "minisweagent": types.SimpleNamespace(),
        "minisweagent.models": types.SimpleNamespace(),
        "minisweagent.models.litellm_model": litellm_model,
        "minisweagent.models.utils": types.SimpleNamespace(),
        "minisweagent.models.utils.actions_toolcall": tools,
    }.items():
        monkeypatch.setitem(sys.modules, name, stub)
    spec = importlib.util.spec_from_file_location("teacher_model", CALIBRATION / "teacher_model.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "teacher_model", module)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout_s):
        self.requests.append(request)
        return json.dumps(REPLY).encode()


ROOMY = SpendCaps(15.0, 1.0)


def model(module, tmp_path, caps=ROOMY):
    transport = FakeTransport()
    session = SparkSession(
        "muse-spark-1.3-contributor", Tier.CONTRIBUTOR, "teacher-spark-t-run1", caps,
        ApiKey("k"), Ledger(tmp_path / "ledger.jsonl"), (module.PUBLIC_ROWS,), transport,
    )  # fmt: skip
    return module.TeacherAgentModel(session=session, label="teacher-spark-t-run1"), transport


def test_each_turn_is_one_capped_ledger_call_with_a_clean_history(monkeypatch, tmp_path):
    module = load(monkeypatch)
    teacher, transport = model(module, tmp_path)
    messages = [{"role": "user", "content": "fix it", "extra": {"x": 1}, "tool_calls": None}]
    response = teacher._query(messages)
    body = json.loads(transport.requests[0].data)
    assert body["messages"] == [{"role": "user", "content": "fix it"}]
    assert body["tools"][0]["function"]["name"] == "bash"
    (entry,) = teacher.session.ledger.entries()
    assert entry["label"] == "teacher-spark-t-run1-t1"
    assert teacher._calculate_cost(response)["cost"] == pytest.approx(entry["cost_usd"])


def test_the_run_cap_stops_the_next_turn_and_aborts_retries(monkeypatch, tmp_path):
    module = load(monkeypatch)
    teacher, transport = model(module, tmp_path, caps=SpendCaps(15.0, 0.0001))
    teacher._query([{"role": "user", "content": "a"}])
    with pytest.raises(SpendCapError):
        teacher._query([{"role": "user", "content": "b"}])
    assert SpendCapError in teacher.abort_exceptions and len(transport.requests) == 1


def test_run_cap_reads_the_environment(monkeypatch):
    module = load(monkeypatch)
    monkeypatch.setenv(module.RUN_CAP_VARIABLE, "0.25")
    assert module.run_cap_usd() == 0.25
    monkeypatch.setenv(module.RUN_CAP_VARIABLE, "lots")
    with pytest.raises(ValueError, match="dollars"):
        module.run_cap_usd()
