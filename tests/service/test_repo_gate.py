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
from symbiont.records.schema import Kind
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog, last_note_event
from symbiont.service.nightly import NightlyJudges
from symbiont.service.onboarding import NIGHTLY_LIVE, ONBOARDING, Lookups
from symbiont.service.repo_gate import RepoGate
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
        gate = RepoGate(self.registry, nightly, Lookups(contexts=store.contexts.all))
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

    assert NIGHTLY_LIVE in rig.start()["announce"]
    assert NIGHTLY_LIVE not in rig.start("second").get("announce", [])


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


def lesson_id_of_fixture():
    from symbiont.miner.trained import lesson_id

    return lesson_id(fixed_failure_lessons()[0])


def post_context(rig, lesson, body):
    return rig.service.respond(f"/lessons/{lesson}/context", body)


def test_a_passing_result_never_gets_a_note_even_after_a_matching_failure(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)
    assert rig.fail()["notes"]

    passed = rig.send(
        "PostToolUse",
        "command",
        "live",
        raw="1 passed",
        command="pytest -q tests/test_parser.py",
        exit_code=0,
    )
    unknown = rig.send(
        "PostToolUse", "command", "live", raw="1 passed", command="pytest -q tests/test_parser.py"
    )

    assert passed["notes"] == [] and unknown["notes"] == []


def test_the_developers_words_lead_the_note_once_saved_through_the_endpoint(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)
    lesson = lesson_id_of_fixture()

    saved = post_context(rig, lesson, {"text": "Keep parser imports lazy.", "priority": "high"})
    (note,) = rig.fail()["notes"]

    assert saved.status == 200 and saved.body["project"] == PROJECT
    assert note.startswith("[symbiont] In this repo: Keep parser imports lazy. Last time")


def test_an_intentional_lesson_is_suppressed(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)
    post_context(rig, lesson_id_of_fixture(), {"text": "on purpose", "intentional": True})

    assert rig.fail() == {"notes": []}


def test_the_context_endpoint_refuses_unknown_lessons_and_bad_payloads(rig):
    lesson = lesson_id_of_fixture()

    assert post_context(rig, "no:such:lesson", {"text": "x"}).status == 404
    assert post_context(rig, lesson, {"text": "x", "priority": "urgent"}).status == 400
    assert post_context(rig, lesson, {"text": "x", "intentional": "yes"}).status == 400
    assert post_context(rig, lesson, {"text": "x", "score": 3}).status == 400
    assert post_context(rig, lesson, {}).status == 400


def test_a_different_assertion_is_not_matched_by_command_and_exception_class_alone(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)

    body = rig.send(
        "PostToolUseFailure",
        "command",
        "live",
        raw="E   assert 1 == 2\nTypeError: x",
        command="pytest -q tests/test_parser.py",
        exit_code=1,
    )

    assert body == {"notes": []}


def test_a_percent_encoded_lesson_id_in_the_path_is_decoded(rig):
    encoded = lesson_id_of_fixture().replace(":", "%3A")

    assert post_context(rig, encoded, {"text": "x"}).status == 200


RULE = "Parser imports stay lazy so startup stays fast."


def with_rule(rig, **extra):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)
    post_context(rig, lesson_id_of_fixture(), {"text": RULE, **extra})


def prompt(rig, text, session_id="live"):
    return rig.send("UserPromptSubmit", "user_turn", session_id, raw=text)


def test_a_rule_reaches_a_prompt_about_a_related_file_and_the_event_says_why(rig):
    with_rule(rig)

    body = prompt(rig, "please speed up app/parser.py")

    assert body["notes"] == [f"[symbiont] In this repo: {RULE.rstrip('.')}."]
    event = last_note_event(rig.runs, PROJECT)
    assert event["fired_by"].startswith("rule: file: ")


def test_a_rule_is_said_once_per_prompt_trigger_in_a_session_and_again_in_the_next(rig):
    with_rule(rig)

    assert prompt(rig, "speed up app/parser.py")["notes"]
    assert prompt(rig, "and tidy app/parser.py again")["notes"] == []
    assert prompt(rig, "speed up app/parser.py", session_id="next")["notes"]


def test_unrelated_work_and_passing_results_get_no_rule_and_the_hold_is_logged(rig):
    with_rule(rig)

    assert prompt(rig, "update the readme badges") == {"notes": []}
    passed = rig.send(
        "PostToolUse",
        "command",
        "live",
        raw="1 passed",
        command="pytest tests/test_parser.py",
        exit_code=0,
    )

    assert passed == {"notes": []}
    held = [json.loads(line) for line in rig.events.path.read_text().splitlines()]
    assert any("unrelated to this work" in str(event.get("note_held")) for event in held)


def test_a_failure_with_a_different_signature_in_a_related_file_gets_the_rule(rig):
    with_rule(rig)

    body = rig.send(
        "PostToolUseFailure",
        "command",
        "live",
        raw="E   assert x is None",
        command="pytest -q tests/test_parser.py",
        exit_code=1,
    )

    (note,) = body["notes"]
    assert note.startswith("[symbiont] In this repo:") and "Last time" not in note


def test_an_exact_failure_still_gets_the_last_time_note_and_a_new_failure_repeats_the_rule(rig):
    with_rule(rig)

    exact = rig.fail()["notes"][0]
    other = rig.send(
        "PostToolUseFailure",
        "command",
        "live",
        raw="E   assert y is None",
        command="pytest tests/test_parser.py",
        exit_code=1,
    )

    assert exact.startswith("[symbiont] In this repo:") and "Last time" in exact
    assert other["notes"] and "Last time" not in other["notes"][0]


def test_an_intentional_rule_is_never_delivered(rig):
    with_rule(rig, intentional=True)

    assert prompt(rig, "speed up app/parser.py") == {"notes": []}


def test_the_context_endpoint_stores_applicability_tags_that_make_a_rule_fire(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)
    lesson = lesson_id_of_fixture()

    saved = post_context(
        rig,
        lesson,
        {
            "text": "Imports stay lazy.",
            "applies_to": {"terms": ["BHD", "credit note"], "areas": []},
        },
    )
    fired = prompt(rig, "Handle the BHD credit note for the team")

    assert saved.status == 200
    assert fired["notes"] == ["[symbiont] In this repo: Imports stay lazy."]
    assert "bhd" in last_note_event(rig.runs, PROJECT)["fired_by"]
    assert post_context(rig, lesson, {"text": "x", "applies_to": {"terms": "BHD"}}).status == 400
    assert post_context(rig, lesson, {"text": "x", "applies_to": {"words": []}}).status == 400


def test_after_yes_the_session_asks_the_focus_question_until_it_is_answered(rig):
    rig.registry.record_stance(PROJECT, RepoStance.GIVEN)

    first = rig.start()["announce"]
    rig.registry.record_focus(PROJECT, {"text": "money", "keywords": ["money"], "sources": []})
    after = rig.start("second").get("announce", [])

    assert any("Anything symbiont should pay attention to" in line for line in first)
    assert any("symbiont_add_lessons" in line for line in first)
    assert not any("pay attention" in line for line in after)


def test_the_dashboard_link_is_shown_once_when_the_repository_has_lessons_and_reviews_are_asked(
    tmp_path,
):
    from symbiont.service.onboarding import Announcements

    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    registry.record_focus(PROJECT, {"text": "x", "keywords": [], "sources": []})
    lookups = Lookups(pending_reviews=lambda project: 3, lesson_count=lambda project: 5)
    news = Announcements(registry, lookups)

    first = news.at_session_start(PROJECT)
    second = news.at_session_start(PROJECT)

    assert any("{dashboard}" in line for line in first)
    assert any("3 pain points" in line and "symbiont_save_reviews" in line for line in first)
    assert not any("{dashboard}" in line for line in second)
    assert (
        Announcements(registry, Lookups(lesson_count=lambda project: 0)).at_session_start(PROJECT)
        == ()
    )


def gate_with(rules, tmp_path):
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    return RepoGate(registry, None, Lookups(written=lambda project: rules))


def test_two_relevant_rules_are_both_said_once_each_and_a_third_is_not(tmp_path):
    from symbiont.miner.lesson_context import AuthoredLesson, LessonKind

    rules = [
        AuthoredLesson(i, f"Rule {i} for the array module.", LessonKind.RULE, (f"pkg/arr/{i}.py",))
        for i in ("a", "b", "c")
    ]
    gate = gate_with(rules, tmp_path)
    record = replace(run("x", 0), project=PROJECT, kind=Kind.USER_TURN, raw="edit pkg/arr/a.py")

    first = gate.speak("s", record, [], [])
    again = gate.speak("s", record, [], [])

    assert len(first.notes) == 2 and first.notes[0].why.startswith("rule: file: ")
    assert len(again.notes) == 1, "the third lesson waits; the two said are not repeated"
    assert gate.speak("s", record, [], []).notes == ()


def test_the_service_answers_with_both_rule_notes_and_logs_each_with_its_match(rig, tmp_path):
    from symbiont.miner.lesson_context import AuthoredLesson, LessonKind

    rules = [
        AuthoredLesson("a", "Indexed conversion keeps order.", LessonKind.RULE, ("pkg/arr/a.py",)),
        AuthoredLesson(
            "b", "Elementwise power uses HadamardPower.", LessonKind.RULE, ("pkg/arr/b.py",)
        ),
    ]
    rig.service = Service(
        ServiceParts(
            Store.open(tmp_path / "other.db"),
            Counters(),
            rig.events,
            ServiceMode.WARN_AND_RECALL,
            gate=gate_with(rules, tmp_path / "reg"),
        )
    )

    body = prompt(rig, "work on pkg/arr/a.py")

    assert [n.split(": ")[1][:7] for n in body["notes"]] == ["Indexed", "Element"]
    events = [json.loads(line) for line in rig.events.path.read_text().splitlines()]
    assert sum("fired_by" in event for event in events) == 2
