"""The repository gate: a repository that did not say yes is not observed, and asked once.

Failures guarded against: Silent Fallback (storing for a repository nobody answered for, or going
mute so the user thinks the plugin is broken) and Paper Tiger (no note on a brand-new repository).
"""

import json
from dataclasses import asdict, replace

import pytest

from record_builders import edit, run, session
from symbiont.core.counters import Counters
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog, last_note_event
from symbiont.service.nightly import NightlyJudges
from symbiont.service.repo_gate import NIGHTLY_LIVE, ONBOARDING, RepoGate
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery

PROJECT = "demo"
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"


def fixed_failure_lessons():
    steps = session(
        run("pytest tests/test_parser.py", 1, IMPORT),
        edit("app/parser.py", diff="-a\n+def parse(text):\n"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    records = [replace(r, project=PROJECT) for r in steps]
    return lessons_from(mine_history(sessions_of(records), {}), records)


class Rig:
    def __init__(self, tmp_path, nightly=None):
        self.registry = RepoRegistry(tmp_path)
        self.events = EventLog(tmp_path / "runs" / "20261102T000000Z", "counters")
        store = Store.open(tmp_path / "store.db")
        store.save_mining(PROJECT, [], fixed_failure_lessons(), held_out_tasks=frozenset())
        gate = RepoGate(self.registry, nightly)
        parts = ServiceParts(store, Counters(), self.events, ServiceMode.WARN_AND_RECALL, gate=gate)
        self.service = Service(parts)
        self.runs = tmp_path / "runs"
        self.step = 40

    def start(self, session_id="live"):
        return self.send("SessionStart", "user_turn", session_id, raw="session started")

    def fail(self, session_id="live", command="pytest -q tests/test_parser.py"):
        return self.send(
            "PostToolUseFailure", "command", session_id, raw=IMPORT, command=command, exit_code=1
        )

    def send(self, event, kind, session_id, **fields):
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
        response = self.service.respond("/observe", body)
        assert response.status == 200, response.body
        return response.body


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_a_repository_nobody_answered_for_is_asked_once_and_nothing_is_stored(rig, tmp_path):
    first = rig.start()
    later = rig.fail()

    assert first["announce"] == [ONBOARDING] and first["notes"] == []
    assert later == {"notes": []}
    assert not rig.events.path.exists(), "an unconsented repository leaves no event"


def test_the_onboarding_says_what_it_does_that_data_stays_local_and_how_to_answer():
    for words in ("warn you about mistakes", "stays on this computer", "symbiont repo allow"):
        assert words in ONBOARDING
    assert "repo mine" in ONBOARDING and "repo decline" in ONBOARDING


def test_a_declined_repository_is_never_asked_again_and_never_observed(rig):
    rig.registry.record_stance(PROJECT, RepoStance.DECLINED)

    assert rig.start() == {"notes": []}
    assert rig.fail() == {"notes": []}
    assert not rig.events.path.exists()


def test_a_consented_repository_gets_the_exact_repeat_note_on_day_one(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)

    body = rig.fail()

    (note,) = body["notes"]
    assert note.startswith("Last time, `pytest tests/test_parser.py` failed with ImportError")
    assert "def parse(text):" in note


def test_the_repeat_note_is_said_once_per_session_and_again_in_the_next(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)

    assert rig.fail()["notes"]
    assert not any("Last time" in n for n in rig.fail()["notes"])
    assert rig.fail(session_id="next")["notes"]


def test_a_muted_trouble_stays_silent(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)
    lesson = fixed_failure_lessons()[0]
    signature = lesson.pain_point.signature
    rig.registry.mute(PROJECT, (signature.signal.value, *signature.key))

    assert rig.fail() == {"notes": []}


def test_the_note_event_names_its_project_and_trouble_so_why_can_find_it(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)
    rig.fail()

    event = last_note_event(rig.runs, PROJECT)

    assert event is not None and event["trouble"][0] == "failed_command"
    assert last_note_event(rig.runs, "someone-else") is None


def test_the_first_night_is_announced_once(tmp_path):
    nightly_dir = tmp_path / "nightly"
    (nightly_dir / PROJECT).mkdir(parents=True)
    (nightly_dir / PROJECT / "nightly.json").write_text("{}")
    rig = Rig(tmp_path, NightlyJudges(nightly_dir))
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)

    assert rig.start()["announce"] == [NIGHTLY_LIVE]
    assert "announce" not in rig.start("second")


def test_status_reports_the_answer_lessons_and_silenced_kinds(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)

    response = rig.service.respond("/status", {"project": PROJECT})

    assert response.body == {
        "project": PROJECT,
        "repo": "given",
        "lessons": 1,
        "muted": 0,
        "nightly": False,
    }
