"""The done-on-red guard: a Stop is held once while the session's last run of a check is red.

Failures guarded against: Silent Fallback (finishing over a red check, or a guard that stays
quiet with no recorded reason), a runaway loop (stop_hook_active), and talking over reflection.
"""

import json
from dataclasses import asdict, replace

import pytest

from record_builders import run
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

    def stop(self, active=False):
        body = {"project": PROJECT, "session_id": "s1", "harness": "muse_code"}
        reply = self.service.respond("/stop/guard", body | {"stop_hook_active": active})
        assert reply.status == 200
        return reply.body

    def events(self):
        lines = [p.read_text() for p in self.dir.glob("runs/*/events.jsonl")]
        rows = [json.loads(x) for text in lines for x in text.splitlines()]
        return [r["stop_guard"] for r in rows if "stop_guard" in r]


def test_red_last_blocks_once_with_the_check_and_the_diff(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(RED)

    first = rig.stop()

    assert first["block"].startswith("The last run of `pytest tests/dialects/test_snowflake.py`")
    assert "- a / + b" in first["block"] and "the work is not done yet" in first["block"]
    assert rig.stop()["block"] == ""
    assert [e["asked"] for e in rig.events()] == [True, False]
    assert "already held once" in rig.events()[1]["why_not"]


def test_red_then_green_does_not_block(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(RED)
    rig.observe(GREEN)

    reply = rig.stop()

    assert reply["block"] == "" and "no failed check" in reply["why_not"]


def test_stop_hook_active_never_blocks_and_is_logged(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(RED)

    reply = rig.stop(active=True)

    assert reply["block"] == "" and "stop_hook_active" in reply["why_not"]
    assert rig.events()[0]["asked"] is False


def test_an_unrelated_failure_does_not_block(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(run("ls missing", 2, "ls: missing: No such file"))

    assert rig.stop()["block"] == ""


def test_the_stop_after_the_guard_hands_on_to_reflection_once(tmp_path):
    rig = Rig(tmp_path)
    rig.observe(RED)
    assert rig.stop()["block"]

    handed = rig.stop(active=True)
    assert handed["after_guard"] is True and handed["block"] == ""
    assert rig.stop(active=True)["after_guard"] is False
