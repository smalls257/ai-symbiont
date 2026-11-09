"""The trained checker is used with no flags, and its role is visible.

A trained repository never gets the ranker's note alone, a down checker says "symbiont checker
offline", and `symbiont why` and the dashboard name the checker that agreed. Fakes only: no
socket, no model, no process.
"""

import json
from dataclasses import replace

import pytest

from judge_builders import PROJECT, QUESTION, URL, judge_saying, recall, service_with
from symbiont import cli
from symbiont.delivery.hooks import offline_note
from symbiont.miner.twins import merge_twins
from symbiont.service.agreed_recall import NOTHING_MATCHES
from symbiont.service.app import Service
from symbiont.service.events import checker_sentences, last_checked_event
from symbiont.service.judge_model import JudgeModel
from symbiont.service.judge_start import JudgeStart, JudgeStartError
from symbiont.service.nightly import RECORD, NightlyJudges, lessons_digest

pytestmark = pytest.mark.periphery

START = JudgeStart("py", "/base", "/adapter", "mps", 8861)


def trained_service(tmp_path, transport, revive=None, with_start=True):
    """A service whose only judge is the repository's nightly record; no first-night judge."""
    base = service_with(tmp_path, None)
    merged = merge_twins(base._parts.store.lessons(PROJECT))
    record = {
        "lessons_digest": lessons_digest(merged),
        "judge_url": URL,
        "lesson_count": 41,
        "trained_at": "2026-11-03T03:00:00+00:00",
        "backend": "mlx",
    }
    if with_start:
        record["judge_start"] = START.as_json()
    (tmp_path / "n" / PROJECT).mkdir(parents=True)
    (tmp_path / "n" / PROJECT / RECORD).write_text(json.dumps(record))
    nightly = NightlyJudges(tmp_path / "n", transport, revive)
    return Service(replace(base._parts, nightly=nightly))


def saying(p_yes):
    return judge_saying(p_yes).transport


def refused(request, timeout_s):
    raise ConnectionRefusedError


def events_of(tmp_path):
    lines = (tmp_path / "run" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_a_service_with_no_flags_looks_in_the_data_dir_for_nightly_records(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "serve", lambda service, port: None)
    monkeypatch.setattr(cli, "open_service", lambda *args: seen.setdefault("guards", args[4]))
    assert cli.main(["serve", "--data-dir", str(tmp_path), "--port", "1"]) == 0
    guards = seen["guards"]
    assert guards.judges.nightly.root == tmp_path / "nightly"
    assert guards.judges.first_night is None and guards.judges.nightly.revive is not None


def test_a_repository_with_no_record_keeps_the_plain_ranker_recall(tmp_path):
    service = trained_service(tmp_path, refused)
    (tmp_path / "n" / PROJECT / RECORD).unlink()
    response = recall(service)
    assert response.status == 200 and response.body["answer"] != NOTHING_MATCHES
    assert not any("checked_by" in event for event in events_of(tmp_path))


def test_a_trained_repository_is_checked_and_the_event_names_the_checker(tmp_path):
    response = recall(trained_service(tmp_path, saying(0.99)))
    assert response.body["answer"].startswith("`tool7 module7` failed")
    checked = next(e["checked_by"] for e in events_of(tmp_path) if "checked_by" in e)
    assert checked == {
        "checker": "Llama 3.2 1B",
        "rule": "nightly",
        "verdict": "agreed",
        "lessons": 41,
        "trained_at": "2026-11-03T03:00:00+00:00",
    }


def test_a_checker_that_says_no_silences_the_note_instead_of_the_ranker_speaking(tmp_path):
    response = recall(trained_service(tmp_path, saying(0.2)))
    assert response.body["answer"] == NOTHING_MATCHES
    assert not any("checked_by" in event for event in events_of(tmp_path))


def test_the_note_and_the_why_sentence_carry_no_probability(tmp_path):
    recall(trained_service(tmp_path, saying(0.9912)))
    event = last_checked_event(tmp_path, PROJECT)
    spoken = json.dumps(event["notes"]) + " ".join(checker_sentences(event))
    assert "0.99" not in spoken and "p_yes" not in spoken
    assert checker_sentences(event) == [
        "The trained checker (Llama 3.2 1B, trained on 41 lessons at 2026-11-03T03:00:00+00:00) "
        "agreed this lesson applies."
    ]


def test_an_event_without_a_checker_adds_no_sentence():
    assert checker_sentences({"notes": ["x"]}) == []


def test_a_down_checker_without_a_start_recipe_says_so_and_names_the_fix(tmp_path):
    response = recall(trained_service(tmp_path, refused, with_start=False))
    assert response.status == 503
    assert response.body["error"].startswith("symbiont checker offline")
    assert "symbiont nightly" in response.body["error"]


class Process:
    def __init__(self):
        self.exit_code = None

    def poll(self):
        return self.exit_code


def test_a_down_checker_is_started_once_while_loading_and_again_after_it_died(tmp_path):
    started = []

    def revive(start, log):
        started.append((start, log))
        return Process()

    service = trained_service(tmp_path, refused, revive)
    first, second = recall(service), recall(service)
    assert started == [(START, tmp_path / "n" / PROJECT / "judge-server.log")]
    assert first.status == second.status == 503
    assert "started it" in first.body["error"] and "still starting" in second.body["error"]
    assert any(e.get("status") == 503 for e in events_of(tmp_path))
    service._agreed._started[PROJECT].exit_code = -9
    assert "started it" in recall(service).body["error"] and len(started) == 2


def test_a_checker_that_cannot_be_started_gives_the_command_to_run_by_hand(tmp_path):
    def cannot(start, log):
        raise JudgeStartError("no such python")

    response = recall(trained_service(tmp_path, refused, cannot))
    error = response.body["error"]
    assert response.status == 503 and "no such python" in error and "--port 8861" in error


def test_a_stale_checker_is_not_started_it_is_retrained(tmp_path):
    service = trained_service(tmp_path, saying(0.99), lambda *_: pytest.fail("started"))
    path = tmp_path / "n" / PROJECT / RECORD
    path.write_text(path.read_text().replace(json.loads(path.read_text())["lessons_digest"], "old"))
    assert "stale" in recall(service).body["error"]


def test_the_offline_line_is_not_prefixed_twice():
    assert offline_note("symbiont checker offline: x") == "symbiont checker offline: x"
    assert offline_note("down") == "symbiont offline: down"


def test_the_dashboard_header_shows_the_last_checked_note(tmp_path):
    service = trained_service(tmp_path, saying(0.99))
    recall(service)
    html = service.page(f"/dashboard?project={PROJECT}").body.decode()
    page = json.loads(html.split('id="symbiont-data">')[1].split("</script>")[0])
    last = page["nightly"]["last_checked"]
    assert (
        last["note"].startswith("`tool7 module7` failed")
        and "trained on 41 lessons" in last["sentence"]
    )


def test_the_question_is_unchanged_plain_text():
    assert JudgeModel(URL) and "tool7" in QUESTION
