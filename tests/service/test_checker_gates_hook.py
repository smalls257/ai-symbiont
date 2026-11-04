"""With a trained checker, a hook-time failure recall is shown only if the checker agrees.

Rules the user or team wrote (house and file rules) are never gated; a repository with no record
is unchanged; a down or slow checker is a visible line, not silence. Fakes only: no socket.
"""

import json
from dataclasses import replace

import pytest

from judge_builders import saying_transport
from record_builders import run
from repo_rig import PROJECT, Rig
from symbiont.core.repeat import RepeatNote
from symbiont.miner.twins import merge_twins
from symbiont.service.events import last_checked_event
from symbiont.service.judge_start import JudgeStart
from symbiont.service.nightly import NightlyJudges, NightlyRecord, lessons_digest, write_record
from symbiont.service.repo_gate import Spoken
from symbiont.store.repos import RepoStance

pytestmark = pytest.mark.periphery

START = JudgeStart("py", "/base", "/adapter", None, 8861)
TRAINED = "2026-11-03T03:00:00+00:00"


class Alive:
    def poll(self):
        return None


def trained_rig(tmp_path, transport, revive=None):
    root = tmp_path / "nightly"
    judges = NightlyJudges(root, transport, revive)
    rig = Rig(tmp_path, judges, judges)
    digest = lessons_digest(merge_twins(rig.lessons()))
    record = NightlyRecord(digest, "http://127.0.0.1:8861", 1, TRAINED, "mlx", START.as_json())
    write_record(root, PROJECT, record)
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)
    return rig


def refused(request, timeout_s):
    raise ConnectionRefusedError


def slow(request, timeout_s):
    raise TimeoutError


def events(rig):
    return [json.loads(x) for x in rig.events.path.read_text(encoding="utf-8").splitlines()]


def test_an_agreeing_checker_lets_the_recall_through_and_the_event_names_it(tmp_path):
    seen = []
    rig = trained_rig(tmp_path, saying_transport(0.99, seen))
    (note,) = rig.fail()["notes"]
    assert note.startswith("Last time, `pytest tests/test_parser.py` failed with ImportError")
    prompt = seen[0]["pairs"][0]["prompt"]
    assert prompt.startswith("Situation:\nRan `pytest -q tests/test_parser.py` in demo (file n/a)")
    assert "ImportError: cannot import name 'parse'" in prompt
    checked = last_checked_event(tmp_path / "runs", PROJECT)["checked_by"]
    assert (checked["rule"], checked["lessons"], checked["trained_at"]) == ("nightly", 1, TRAINED)


def test_a_disagreeing_checker_means_no_note_and_the_event_log_says_why(tmp_path):
    rig = trained_rig(tmp_path, saying_transport(0.2))
    assert rig.fail() == {"notes": []}
    held = next(e["note_held"] for e in events(rig) if "note_held" in e)
    assert held["why"] == "nightly:judge_too_low" and "ImportError" not in json.dumps(held)


def test_a_down_checker_is_a_visible_line_and_the_note_is_retried_next_time(tmp_path):
    started = []

    def revive(start, log):
        started.append(start)
        return Alive()

    rig = trained_rig(tmp_path, refused, revive)
    down = rig.fail_response()
    assert down.status == 503 and down.body["error"].startswith("symbiont checker offline")
    assert started == [START]
    parts = rig.service._parts
    working = replace(parts.nightly, transport=saying_transport(0.99))
    rig.service._parts = replace(parts, nightly=working)
    rig.service._agreed._parts = rig.service._parts
    assert rig.fail()["notes"], "the once-per-session mark was withdrawn while the checker was down"


def test_a_checker_slower_than_the_hook_budget_is_said_aloud_and_not_restarted(tmp_path):
    rig = trained_rig(tmp_path, slow, lambda *_: pytest.fail("a slow checker is alive"))
    response = rig.fail_response()
    assert response.status == 503
    assert response.body["error"].startswith("symbiont checker slow:")
    assert "no note was shown" in response.body["error"]


def test_rules_the_user_wrote_are_never_gated(tmp_path):
    rig = trained_rig(tmp_path, lambda *_: pytest.fail("judge called for a rule"))
    rule = Spoken((RepeatNote("[symbiont] rule", rig.lessons()[0], "rule: tag: x (+1)"),))
    kept, checked = rig.service._agreed.vet(None, run("x", 1), rule, rig.lessons())
    assert kept is rule and checked is None


def test_with_no_nightly_record_the_recall_is_unchanged_and_no_judge_is_called(tmp_path):
    rig = trained_rig(tmp_path, lambda *_: pytest.fail("judge called"))
    (tmp_path / "nightly" / PROJECT / "nightly.json").unlink()
    assert rig.fail()["notes"]
