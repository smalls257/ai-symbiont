"""Session-end reflection: asked once, only in a consented repository, only after real work.

Failures guarded against: Silent Fallback (an empty reply that hides why no question was asked),
a runaway loop (the reflection turn ends in another Stop), and storing or asking in a repository
nobody allowed (privacy).
"""

import json
from dataclasses import asdict, replace

import pytest

from record_builders import edit, run
from symbiont.records.schema import Kind
from symbiont.service.app import ServiceMode
from symbiont.service.reflection import REFLECTION_LABEL, REFLECTION_QUESTION
from symbiont.service.wiring import Guards, open_service
from symbiont.store.local import Store
from symbiont.store.reflections import ReflectionLedger
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery
PROJECT = "demo"


class Rig:
    def __init__(self, tmp_path, *, allow=True):
        self.dir = tmp_path
        self.registry = RepoRegistry(tmp_path)
        if allow:
            self.registry.record_stance(PROJECT, RepoStance.GIVEN)
        self.service = open_service(tmp_path, ServiceMode.WARN_AND_RECALL, guards=self.guards())
        self.step = 0

    def guards(self):
        return Guards(repos=self.registry)

    def observe(self, record, session_id="s1", event="PostToolUse"):
        self.step += 1
        record = replace(record, project=PROJECT, session_id=session_id, step=self.step)
        body = {
            "harness": "claude_code",
            "session_id": session_id,
            "event": event,
            "payload": {"record": json.loads(json.dumps(asdict(record)))},
        }
        reply = self.service.respond("/observe", body)
        assert reply.status == 200
        return reply.body

    def reflect(self, session_id="s1", project=PROJECT):
        body = {"project": project, "session_id": session_id, "harness": "claude_code"}
        return self.service.respond("/reflect", body)


def test_a_session_that_edited_in_a_consented_repository_is_asked_the_question(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(edit("src/billing/refund.py"))

    reply = rig.reflect()

    assert reply.status == 200 and reply.body == {"ask": REFLECTION_QUESTION}
    assert "non-obvious" in REFLECTION_QUESTION and "symbiont_add_lessons" in REFLECTION_QUESTION
    assert f'"{REFLECTION_LABEL}"' in REFLECTION_QUESTION


def test_the_same_session_is_asked_only_once_and_the_next_session_again(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(edit("a.py"))
    rig.observe(edit("a.py"), session_id="s2")

    assert rig.reflect().body["ask"]
    again = rig.reflect().body
    assert again["ask"] == "" and "already asked" in again["why_not"]
    assert rig.reflect(session_id="s2").body["ask"]


def test_the_once_per_session_guard_survives_a_service_restart(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(edit("a.py"))
    assert rig.reflect().body["ask"]

    restarted = Rig(tmp_path)
    restarted.observe(edit("a.py"))

    assert "already asked" in restarted.reflect().body["why_not"]


def test_a_repository_nobody_allowed_is_not_asked_and_nothing_is_marked(tmp_path):
    rig = Rig(tmp_path, allow=False)
    rig.observe(edit("a.py"))

    reply = rig.reflect().body

    assert reply["ask"] == "" and "not switched on" in reply["why_not"]
    assert not ReflectionLedger(rig.dir).asked(PROJECT, "s1")


def test_a_declined_repository_is_not_asked(tmp_path):
    rig = Rig(tmp_path, allow=False)
    rig.registry.record_stance(PROJECT, RepoStance.DECLINED)

    assert "not switched on" in rig.reflect().body["why_not"]


def test_a_session_that_changed_no_file_has_nothing_to_reflect_on_and_says_so(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(run("pytest -q", 0, "1 passed"))

    reply = rig.reflect().body

    assert reply["ask"] == "" and "changed no file" in reply["why_not"]
    assert not ReflectionLedger(rig.dir).asked(PROJECT, "s1")


def test_without_a_registry_there_is_no_consent_and_no_question(tmp_path):
    service = open_service(tmp_path, ServiceMode.WARN_AND_RECALL)
    body = {"project": PROJECT, "session_id": "s1", "harness": "claude_code"}

    reply = service.respond("/reflect", body).body

    assert reply["ask"] == "" and "consent" in reply["why_not"]


def test_a_malformed_reflect_request_is_a_400(tmp_path):
    rig = Rig(tmp_path)

    refused = rig.service.respond("/reflect", {"project": PROJECT, "mode": "loud"})

    assert refused.status == 400


def test_reflected_lessons_are_stored_labelled_and_speak_when_their_area_comes_up(tmp_path):
    rig = Rig(tmp_path)
    saved = rig.service.respond(
        "/lessons/add",
        {
            "project": PROJECT,
            "lessons": [
                {
                    "text_in_plain_words": "Refund totals are rounded once, in ledger.py, "
                    "never in the invoice view.",
                    "kind": "rule",
                    "files": ["src/billing/ledger.py"],
                    "source_label": REFLECTION_LABEL,
                    "applies_to": {"terms": ["refund"], "areas": ["src/billing"]},
                }
            ],
        },
    )
    assert saved.status == 200 and saved.body["added"] == 1

    (stored,) = Store.open(tmp_path / "store.db").curation.authored(PROJECT)
    assert stored.source_label == REFLECTION_LABEL and stored.kind.value == "rule"
    prompt = replace(run("x"), kind=Kind.USER_TURN, raw="fix the total in src/billing/ledger.py")

    told = rig.observe(prompt, event="UserPromptSubmit")

    assert any("rounded once, in ledger.py" in note for note in told["notes"])
