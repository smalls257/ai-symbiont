"""Route A offline replay: reader rows, the gold-line guard, and a run through a live service.

Violation prevented: Paper Tiger. A replay that typed its classifier panel or its notes would show
a decision nobody made, so the end-to-end test posts a synthetic run to a real `Service` over
loopback HTTP (logistic warner, fake memory server) and checks each entry against the event log
the service wrote; a memory model that replies outside the form must stop the replay, never
leave a blank note.
"""

import argparse
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from symbiont.core.features import N_FEATURES
from symbiont.core.warner import LogisticWarner, WarnerWeights
from symbiont.delivery.recall import ServiceOfflineError
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.readers.mini_swe_agent import read_local_run
from symbiont.records.schema import Kind
from symbiont.service import server
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.wiring import open_memory
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery  # loopback sockets and temp files

ROOT = Path(__file__).resolve().parents[2]
ROUTEA = ROOT / "scripts" / "routea"
TASK = "tobymao__sqlglot-9999"
LINE = "Happened: `pytest` failed -> Resolved: you fixed the import -> Check: `pytest -q`"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(ROUTEA))
rows = load("replay_rows", ROUTEA / "replay_rows.py")
replay = load("build_routea_replay", ROUTEA / "build_routea_replay.py")
contract = load("demo_contract", ROOT / "tests" / "dashboard" / "test_demo_contract.py")


def call(command, at):
    usage = {"prompt_tokens": 100, "completion_tokens": 10}
    timings = {"prompt_ms": 1000, "predicted_ms": 1000}
    response = {"usage": usage, "timings": timings}
    extra = {"actions": [{"command": command}], "timestamp": at, "response": response}
    return {"role": "assistant", "content": "", "extra": extra}


def result(at, returncode, output):
    content = f"<returncode>{returncode}</returncode>\n<output>\n{output}</output>"
    extra = {"timestamp": at + 0.5, "returncode": returncode, "raw_output": output}
    return {"role": "tool", "content": content, "extra": extra}


FAILING = ("python -m pytest tests/test_x.py", 1, "Traceback\nImportError: no module x")


def trajectory(steps=10, failing_at=(2, 3, 9)):
    """A capped run; the steps in `failing_at` fail the same test run, the rest list files."""
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "the task"}]
    for step in range(1, steps + 1):
        command, code, output = FAILING if step in failing_at else ("ls", 0, "a.py")
        messages += [call(command, step), result(step, code, output)]
    return {"messages": [*messages, {"role": "exit", "content": "LimitsExceeded"}]}


def test_reader_row_keeps_every_command_and_exit_code(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(rows.reader_row(trajectory(), "r/1", TASK)) + "\n")
    records = list(read_local_run(path, "sqlglot"))
    commands = [r for r in records if r.kind is Kind.COMMAND]
    assert records[0].kind is Kind.USER_TURN and len(commands) == 10
    assert [r.exit_code for r in commands][:3] == [0, 1, 1]
    assert commands[1].command == FAILING[0]


def test_reader_row_refuses_an_unknown_role():
    broken = {"messages": [{"role": "critic", "content": "x"}]}
    with pytest.raises(rows.TrajectoryShapeError, match="critic"):
        rows.reader_row(broken, "r/1", TASK)


def test_history_skips_the_replayed_task(tmp_path):
    for task in (TASK, "tobymao__sqlglot-1"):
        folder = tmp_path / "runs" / "traj" / task
        folder.mkdir(parents=True)
        (folder / "confirm-run2-low.traj.json").write_text(json.dumps(trajectory()))
    found = rows.trajectory_files([tmp_path / "runs"], TASK)
    assert [p.parent.name for p in found] == ["tobymao__sqlglot-1"]


def lesson(quote, resolution=()):
    pain = PainPoint(Signature(Signal.FAILED_COMMAND, ("pytest", "-", "exit 1")), "s", 1, ())
    return Lesson(pain, quote, tuple(resolution), None, spark_safe=True, sources=())


def test_gold_guard_refuses_a_lesson_that_quotes_the_fix():
    gold = rows.gold_lines("--- a/x.py\n+++ b/x.py\n+    VAR_SINGLE_TOKENS = {'#'}\n+)\n")
    assert gold == {"VAR_SINGLE_TOKENS = {'#'}"}
    assert rows.refuse_gold_leaks([lesson("pytest failed")], gold) == 1
    leaking = lesson("x", ["ran sed to add VAR_SINGLE_TOKENS = {'#'} here"])
    with pytest.raises(rows.GoldLineLeakError, match="1 lessons"):
        rows.refuse_gold_leaks([leaking], gold)


def test_note_parts_are_bounded_and_marked_when_cut():
    long = " ".join(f"w{i}" for i in range(20))
    assert replay.bounded(long).split() == [*long.split()[:11], "[...]"]
    assert len(replay.bounded("x" * 200)) <= replay.MAX_PART_CHARS
    assert replay.bounded("short part") == "short part"


def test_a_line_outside_the_three_part_form_is_refused():
    with pytest.raises(replay.ReplayError, match="three-part"):
        replay.note_entry("Happened: x -> Check: y")


def memory_server(text):
    class Routes(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            payload = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Routes)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def always_risky():
    coef = np.zeros(N_FEATURES + 1)
    coef[0] = 5.0
    return LogisticWarner(WarnerWeights(np.zeros(N_FEATURES), np.ones(N_FEATURES), coef, 0.5))


def trained_memory_dir(tmp_path):
    memory = tmp_path / "memory"
    (memory / "adapter").mkdir(parents=True)
    (memory / "adapter" / "adapters.safetensors").write_text("{}")
    (memory / "manifests").mkdir()
    (memory / "manifests" / "m.json").write_text(json.dumps({"project": "sqlglot"}))
    (memory / "adapter.json").write_text(json.dumps({"model": "m", "provenance": "public"}))
    return memory


def start_service(tmp_path, text):
    """A loopback service (always-risky warner) over a fake memory server answering `text`."""
    memory_httpd = memory_server(text)
    url = f"http://127.0.0.1:{memory_httpd.server_address[1]}"
    memory = open_memory(url, trained_memory_dir(tmp_path))
    events = EventLog(tmp_path / "events", "logistic")
    store = Store.open(tmp_path / "store.db")
    parts = ServiceParts(store, always_risky(), events, ServiceMode.WARN_AND_RECALL, memory=memory)
    httpd = server.bind(Service(parts), 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1], events.path


@pytest.fixture
def replay_args(tmp_path):
    """Builds the replay's arguments against a fresh service whose memory answers `text`."""
    traj = tmp_path / "t.traj.json"
    traj.write_text(json.dumps(trajectory()))
    target = tmp_path / "t.jsonl"
    target.write_text(json.dumps(rows.reader_row(trajectory(), "runs/t/2", TASK)) + "\n")
    grades = tmp_path / "calibration.jsonl"
    graded = [{"instance_id": TASK, "run": n, "steps": 10, "resolved": n == 1} for n in (1, 2)]
    grades.write_text("".join(json.dumps(g) + "\n" for g in graded))

    def args_for(text=LINE):
        port, events = start_service(tmp_path, text)
        return argparse.Namespace(
            trajectory=traj, rows=target, grades=grades, task=TASK, run=2, label="A task",
            port=port, events=events,
        )  # fmt: skip

    return args_for


def test_replay_shows_the_logged_decisions_and_the_memory_model_notes(replay_args):
    document, costs = replay.build(replay_args())
    schema = contract._load("demo-replay.schema.json")
    assert contract.violations(document, schema, schema) == []
    plain, routea = document["runs"]
    assert all(s["classifier"] is None and s["note"] is None for s in plain["steps"])
    verdicts = [s["classifier"]["speak"] for s in routea["steps"]]
    # Option A: speaks at the first failure, holds the next (too recent), speaks again later.
    assert [i + 1 for i, v in enumerate(verdicts) if v == "speak"] == [2, 9]
    assert "held by the note rule" in routea["steps"][2]["classifier"]["reason"]
    assert all(len(s["classifier"]["reason"].split()) <= 12 for s in routea["steps"])
    assert routea["steps"][0]["classifier"]["reason"] == "Not a pause a hook can speak at."
    noted = [s for s in routea["steps"] if s["note"]]
    assert [s["step"] for s in noted] == [2, 9]
    assert noted[0]["note"] == {
        "what": "`pytest` failed",
        "resolved": "you fixed the import",
        "check": "pytest -q",
        "source": replay.NOTE_SOURCE,
    }
    assert [c["step"] for c in costs] == [2, 9] and all(c["ms"] >= 0 for c in costs)
    assert plain["totals"] == {**routea["totals"], "notes": 0}
    assert (plain["runs_solved"], plain["runs_total"], plain["shown_run"]) == (1, 2, 2)


def test_a_memory_reply_outside_the_form_stops_the_replay(replay_args):
    with pytest.raises(ServiceOfflineError):
        replay.build(replay_args("I do not remember."))


def test_a_trajectory_that_disagrees_with_the_grader_is_refused(replay_args):
    args = replay_args()
    args.run = 1  # the grader says run 1 was solved; this trajectory never submits
    with pytest.raises(replay.TrajectoryError):
        replay.build(args)


def test_shipped_routea_replay_matches_the_schema_and_its_label():
    files = sorted((ROOT / "dashboard" / "sample").glob("routea-replay-*.json"))
    assert files
    schema = contract._load("demo-replay.schema.json")
    for path in files:
        document = json.loads(path.read_text())
        assert contract.violations(document, schema, schema) == []
        steps = document["runs"][1]["steps"]
        assert all(s["classifier"] is not None for s in steps)
        assert {s["note"]["source"] for s in steps if s["note"]} == {replay.NOTE_SOURCE}
        spoke = [s["step"] for s in steps if s["classifier"]["speak"] == "speak"]
        assert spoke == [s["step"] for s in steps if s["note"]]
