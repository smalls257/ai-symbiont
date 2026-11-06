"""A service rig over one stored, fixed failure: hooks in, notes out (for gate tests)."""

import json
from dataclasses import asdict, replace

from record_builders import edit, run, session
from store_builders import save_lessons
from symbiont.core.counters import Counters
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.onboarding import Lookups
from symbiont.service.repo_gate import RepoGate
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry

PROJECT = "demo"
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"


def fixed_failure_lessons():
    steps = session(
        run("pytest tests/test_parser.py", 1, IMPORT),
        edit("app/parser.py", diff="-a\n+def parse(text):\n"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    records = [replace(r, project=PROJECT) for r in steps]
    return lessons_from(mine_history(sessions_of(records), {}), records, frozenset())


class Rig:
    def __init__(self, tmp_path, nightly=None, judges=None):
        self.registry = RepoRegistry(tmp_path)
        self.events = EventLog(tmp_path / "runs" / "20261102T000000Z", "counters")
        store = Store.open(tmp_path / "store.db")
        save_lessons(store, PROJECT, [], fixed_failure_lessons(), held_out_tasks=frozenset())
        gate = RepoGate(self.registry, nightly, Lookups(contexts=store.contexts.all))
        parts = ServiceParts(
            store, Counters(), self.events, ServiceMode.WARN_AND_RECALL, nightly=judges, gate=gate
        )
        self.service = Service(parts)
        self.store = store
        self.runs = tmp_path / "runs"
        self.step = 40

    def lessons(self):
        return self.store.lessons(PROJECT)

    def start(self, session_id="live"):
        return self.send("SessionStart", "user_turn", session_id, raw="session started")

    def fail(self, session_id="live", command="pytest -q tests/test_parser.py"):
        return self.send(
            "PostToolUseFailure", "command", session_id, raw=IMPORT, command=command, exit_code=1
        )

    def send(self, event, kind, session_id, **fields):
        response = self.respond(event, kind, session_id, **fields)
        assert response.status == 200, response.body
        return response.body

    def fail_response(self, session_id="live", command="pytest -q tests/test_parser.py"):
        """The service's full response to a failing command (a refusal is not asserted away)."""
        fields = {"raw": IMPORT, "command": command, "exit_code": 1}
        return self.respond("PostToolUseFailure", "command", session_id, **fields)

    def respond(self, event, kind, session_id, **fields):
        self.step += 1
        base = run("x", 0)
        record = replace(base, project=PROJECT, session_id=session_id, step=self.step)
        record = replace(record, **{"kind": kind, "command": None, **fields})
        body = {
            "harness": "claude_code",
            "session_id": session_id,
            "event": event,
            "payload": {"record": json.loads(json.dumps(asdict(record)))},
        }
        return self.service.respond("/observe", body)
