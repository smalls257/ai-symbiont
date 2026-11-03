"""The done-on-red guard: a Stop is held once while the session's last run of a check is red.

Failures guarded against: Silent Fallback (finishing over a red check, or a guard that stays
quiet with no recorded reason), a runaway loop (stop_hook_active), and talking over reflection.
"""

import json
from dataclasses import asdict, replace

import pytest

from record_builders import edit, run
from symbiont.service.app import ServiceMode
from symbiont.service.wiring import Guards, open_service
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery
PROJECT = "demo"
RED = run("pytest tests/dialects/test_snowflake.py", 1, "E   - a\nE   + b\n1 failed in 0.3s")
GREEN = run("pytest tests/dialects/test_snowflake.py", 0, "3 passed in 0.3s")


class Rig:
    def __init__(self, tmp_path):
        self.dir = tmp_path
        registry = RepoRegistry(tmp_path)
        registry.record_stance(PROJECT, RepoStance.GIVEN)
        self.service = open_service(
            tmp_path, ServiceMode.WARN_AND_RECALL, guards=Guards(repos=registry)
        )
        self.step = 0

    def observe(self, record):
        self.step += 1
        record = replace(record, project=PROJECT, session_id="s1", step=self.step)
        body = {
            "harness": "muse_code",
            "session_id": "s1",
            "event": "PostToolUse",
            "payload": {"record": json.loads(json.dumps(asdict(record)))},
        }
        assert self.service.respond("/observe", body).status == 200

    def body(self):
        return {"project": PROJECT, "session_id": "s1", "harness": "muse_code"}

    def stop(self, active=False):
        reply = self.service.respond("/stop/guard", self.body() | {"stop_hook_active": active})
        assert reply.status == 200
        return reply.body

    def events(self):
        lines = [p.read_text() for p in self.dir.glob("runs/*/events.jsonl")]
        rows = [json.loads(x) for text in lines for x in text.splitlines()]
        return [r["stop_guard"] for r in rows if "stop_guard" in r]


def test_red_last_blocks_with_the_check_and_the_diff(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(RED)

    first = rig.stop()

    assert first["block"].startswith("The last run of `pytest tests/dialects/test_snowflake.py`")
    assert "- a / + b" in first["block"] and "the work is not done yet" in first["block"]
    assert [e["asked"] for e in rig.events()] == [True]


def test_red_then_green_does_not_block(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(RED)
    rig.observe(GREEN)

    reply = rig.stop()

    assert reply["block"] == "" and "no failed check" in reply["why_not"]


def test_an_unrelated_failure_does_not_block(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(run("ls missing", 2, "ls: missing: No such file"))

    assert rig.stop()["block"] == ""


def test_muse_sequence_stop_hook_active_true_on_every_stop_after_the_first_block(tmp_path):
    """sqB2-ci-2: Stop 1 active=false; every later Stop active=true. The guard fired once, then
    the model re-ran the check, it stayed red, and the final Stop (active=true) was let through."""
    rig = Rig(tmp_path)
    rig.observe(RED)
    assert rig.stop(active=False)["block"]
    assert rig.stop(active=True)["block"] == "", "same failure, nothing newer: no repeat hold"

    rig.observe(RED)
    again = rig.stop(active=True)

    assert again["block"].startswith("The last run of"), "a newer red run is held despite the flag"
    rig.observe(RED)
    assert rig.stop(active=True)["block"] == "", "never a third hold"
    assert [e["asked"] for e in rig.events()] == [True, False, True, False]
    assert all(e["host_stop_hook_active"] in (True, False) for e in rig.events())


def test_the_reflection_turns_stop_is_never_held(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(edit("a.py"))
    rig.observe(GREEN)
    assert rig.service.respond("/reflect", rig.body()).body["ask"]
    rig.observe(RED)

    reply = rig.stop(active=True)

    assert reply["block"] == "" and reply["reflecting"] is True
    rig.service.respond("/reflect/finished", rig.body())
    assert rig.stop(active=True)["block"], "after the reflection, a red check is held again"
