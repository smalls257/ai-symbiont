"""/recall under the agree rule: stored note verbatim when ranker and judge agree, else silence.

Violation prevented: Silent Fallback. A down judge is a 503 ("symbiont offline"), never an empty
or best-guess note. The judge servers are fakes; no socket opens.
"""

import json
from dataclasses import asdict, replace

import pytest

from record_builders import run
from symbiont.core.counters import Counters
from symbiont.egress import EgressRefusedError
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.twins import merge_twins
from symbiont.service.app import NOTHING_MATCHES, Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.judge_model import JudgeModel, JudgeOfflineError
from symbiont.service.nightly import RECORD, NightlyJudges, lessons_digest
from symbiont.store.local import Source, Store

pytestmark = pytest.mark.periphery

PROJECT = "demo"
URL = "http://127.0.0.1:8791"
QUESTION = "tool7 module7 failed with Oops7 again, what now?"


def lesson(index, fix):
    signature = Signature(Signal.FAILED_COMMAND, (f"tool{index}", f"module{index}", f"Oops{index}"))
    pain = PainPoint(signature, f"s{index}", 1, ((f"s{index}", 1),))
    return Lesson(
        pain, f"$ tool{index} module{index}\nOops{index}", (fix,), None, True, pain.record_refs
    )


def judge_saying(p_yes):
    def transport(request, timeout_s):
        return json.dumps({"p_yes": [p_yes]}).encode()

    return JudgeModel(URL, transport)


def service_with(tmp_path, judge):
    store = Store.open(tmp_path / "store.db")
    lessons = [lesson(index, "ran `a`") for index in range(40)] + [lesson(7, "ran `b`")]
    store.save_mining(
        PROJECT, [Source(PROJECT, "claude_code", "x")], lessons, held_out_tasks=frozenset()
    )
    parts = ServiceParts(
        store, Counters(), EventLog(tmp_path / "run", "c"), ServiceMode.RECALL_ONLY, judge=judge
    )
    return Service(parts)


def recall(service):
    return service.respond("/recall", {"question": QUESTION, "project": PROJECT})


def test_agreement_returns_the_stored_note_with_both_twins_fixes(tmp_path):
    answer = recall(service_with(tmp_path, judge_saying(0.99))).body["answer"]
    assert "ran `a`" in answer and "ran `b`" in answer and answer.startswith("What happened: ")


def test_a_judge_under_the_bar_gives_the_plain_nothing_matches(tmp_path):
    assert recall(service_with(tmp_path, judge_saying(0.5))).body["answer"] == NOTHING_MATCHES


def test_a_judge_that_is_down_is_a_503_never_an_empty_note(tmp_path):
    def down(request, timeout_s):
        raise ConnectionRefusedError

    response = recall(service_with(tmp_path, JudgeModel(URL, down)))
    assert response.status == 503 and "judge at" in response.body["error"]


@pytest.mark.parametrize("reply", [{"p_yes": []}, {"oops": 1}, {"p_yes": [1.5]}, {"p_yes": [True]}])
def test_a_reply_without_a_probability_is_offline_not_a_zero(reply):
    def odd(request, timeout_s):
        return json.dumps(reply).encode()

    with pytest.raises(JudgeOfflineError):
        JudgeModel(URL, odd).p_yes("x")


def test_the_judge_must_be_on_loopback():
    with pytest.raises(EgressRefusedError):
        JudgeModel("http://example.com:1")


def nightly_service(tmp_path, digest, p_yes=0.99):
    base = service_with(tmp_path, judge_saying(0.5))
    if digest is not None:
        merged = merge_twins(base._parts.store.lessons(PROJECT))
        record = {"lessons_digest": digest or lessons_digest(merged), "judge_url": URL}
        (tmp_path / "n" / PROJECT).mkdir(parents=True)
        (tmp_path / "n" / PROJECT / RECORD).write_text(json.dumps(record))
    nightly = NightlyJudges(tmp_path / "n", judge_saying(p_yes).transport)
    return Service(replace(base._parts, nightly=nightly))


def test_after_the_first_night_the_repos_own_adapter_judges_with_no_ranker_cut(tmp_path):
    service = nightly_service(tmp_path, digest="")
    answer = service.respond("/recall", {"question": "tool7", "project": PROJECT}).body["answer"]
    assert answer.startswith("What happened: ")


def test_the_nightly_bar_is_stricter_than_the_agree_bar(tmp_path):
    service = nightly_service(tmp_path, digest="", p_yes=0.97)
    assert recall(service).body["answer"] == NOTHING_MATCHES


def test_before_the_first_night_the_agree_rule_decides(tmp_path):
    service = nightly_service(tmp_path, digest=None)
    assert recall(service).body["answer"] == NOTHING_MATCHES


def test_a_stale_nightly_adapter_is_a_503_not_a_fallback(tmp_path):
    response = recall(nightly_service(tmp_path, digest="old"))
    assert response.status == 503 and "stale" in response.body["error"]


def observe_action(service, command, exit_code, step):
    record = replace(run(command, exit_code), project=PROJECT, session_id="live", step=step)
    body = {
        "harness": "claude_code",
        "session_id": "live",
        "event": "PostToolUse",
        "payload": {"record": json.loads(json.dumps(asdict(record)))},
    }
    assert service.respond("/observe", body).status == 200


def test_a_shown_note_is_logged_with_its_rule_and_the_next_three_actions(tmp_path):
    service = service_with(tmp_path, judge_saying(0.99))
    assert recall(service).body["answer"].startswith("What happened: ")
    for step, (command, code) in enumerate([("ls", 0), ("a", 0), ("make", 2)]):
        observe_action(service, command, code, step)
    events = [json.loads(x) for x in (tmp_path / "run" / "events.jsonl").read_text().splitlines()]
    shown = next(e["note_shown"] for e in events if "note_shown" in e)
    done = next(e["note_outcome"] for e in events if "note_outcome" in e)
    assert shown == {"note_id": "s7:1", "rule": "agree"}
    assert done == {
        "note_id": "s7:1",
        "rule": "agree",
        "actions": ["ignored", "followed", "burned"],
    }
