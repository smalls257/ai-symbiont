"""House rules reach the agent through the service; a stale reflection stays silent and says why.

Violations guarded against: Paper Tiger (a correction with no matching words never heard) and
Black Box (a lesson that stopped firing with nothing in the log to explain it).
"""

import argparse
import json
from dataclasses import asdict, replace

import pytest

from record_builders import run
from symbiont.core.counters import Counters
from symbiont.core.rule_relevance import MAX_RULE_NOTES
from symbiont.miner.lesson_context import AuthoredLesson, LessonKind
from symbiont.records.schema import Kind
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.onboarding import Lookups
from symbiont.service.operator_commands import _why
from symbiont.service.repo_gate import RepoGate
from symbiont.service.supersessions import SHOWN, superseded_sentences
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery

PROJECT = "parcels"
REFLECTION = (
    "Parcel labels are priced from the stored zone table, never from the live carrier quote, "
    "so a label total is stable when it is reprinted."
)
CORRECTION = "Price a parcel label from the live carrier quote, not from the stored zone table."
SEALS = "Every sealed carton gets a seal_log entry with its carton number."
PRICING_PROMPT = "Add a surcharge to the parcel label price for remote zones."
UNRELATED_PROMPT = "Rename the packing slip header to include the date."


class Rig:
    def __init__(self, tmp_path, lessons):
        registry = RepoRegistry(tmp_path)
        registry.record_stance(PROJECT, RepoStance.GIVEN)
        self.events = EventLog(tmp_path / "runs" / "20261103T000000Z", "counters")
        gate = RepoGate(registry, None, Lookups(written=lambda project: lessons))
        parts = ServiceParts(
            Store.open(tmp_path / "s.db"),
            Counters(),
            self.events,
            ServiceMode.WARN_AND_RECALL,
            gate=gate,
        )
        self.service = Service(parts)
        self.runs = tmp_path / "runs"
        self.step = 0

    def prompt(self, text, session_id="s1"):
        self.step += 1
        record = replace(
            run("x", 0),
            project=PROJECT,
            session_id=session_id,
            step=self.step,
            kind=Kind.USER_TURN,
            command=None,
            raw=text,
        )
        body = {
            "harness": "claude_code",
            "session_id": session_id,
            "event": "UserPromptSubmit",
            "payload": {"record": json.loads(json.dumps(asdict(record)))},
        }
        response = self.service.respond("/observe", body)
        assert response.status == 200, response.body
        return response.body["notes"]

    def logged(self):
        lines = self.events.path.read_text().splitlines()
        return [json.loads(line) for line in lines]


def correction(ident, text):
    return AuthoredLesson(ident, text, LessonKind.CORRECTION, (), f"correction s0:{ident}")


def reflection(ident=" refl", text=REFLECTION):
    return AuthoredLesson(
        ident.strip(), text, LessonKind.RULE, ("labels/price.py",), "from reflection"
    )


def test_a_correction_without_terms_reaches_an_unrelated_first_prompt_once_per_session(tmp_path):
    rig = Rig(tmp_path, [correction("seal", SEALS)])

    first = rig.prompt(UNRELATED_PROMPT)

    assert first == [f"[symbiont] House rules you gave in this repo: {SEALS}"]
    assert rig.prompt("and the footer too", session_id="s1") == []
    assert rig.prompt(UNRELATED_PROMPT, session_id="s2") == first


def test_the_house_rules_event_names_the_lessons_that_spoke(tmp_path):
    rig = Rig(tmp_path, [correction("seal", SEALS)])

    rig.prompt(UNRELATED_PROMPT)

    spoke = [event for event in rig.logged() if event.get("notes")]
    assert spoke[0]["fired_by"] == "rule: house rules (seal)"


def test_at_most_three_corrections_are_said_and_the_note_cap_still_holds(tmp_path):
    many = [correction(f"c{n}", f"Carton rule number {n} for the dock.") for n in range(6)]
    rig = Rig(tmp_path, many)

    notes = rig.prompt(UNRELATED_PROMPT)

    assert len(notes) <= MAX_RULE_NOTES
    assert notes[0].count("Carton rule number") == 3
    assert "number 5" in notes[0] and "number 2" not in notes[0]


def test_a_correction_already_firing_on_the_words_is_not_said_twice(tmp_path):
    rig = Rig(tmp_path, [correction("price", CORRECTION), correction("seal", SEALS)])

    notes = rig.prompt(PRICING_PROMPT)

    joined = " ".join(notes)
    assert joined.count("live carrier quote") == 1
    assert SEALS in joined


def test_a_reflection_written_before_a_contradicting_correction_never_fires(tmp_path):
    rig = Rig(tmp_path, [reflection(), correction("price", CORRECTION)])

    notes = rig.prompt(PRICING_PROMPT)

    assert all("stored zone table, never" not in note for note in notes)
    assert any("live carrier quote" in note for note in notes)
    assert rig.prompt("price labels for remote zones", session_id="s2") != []


def test_the_supersession_is_an_event_and_why_shows_it(tmp_path, capsys):
    rig = Rig(tmp_path, [reflection(), correction("price", CORRECTION)])
    rig.prompt(PRICING_PROMPT)

    entries = [event["superseded"] for event in rig.logged() if "superseded" in event]
    assert entries[0][0]["lesson"] == "refl" and entries[0][0]["by"] == "price"
    assert _why(argparse.Namespace(data_dir=tmp_path, project=PROJECT)) == 0
    shown = capsys.readouterr().out
    assert "Held back as out of date" in shown and "stored zone table, never" in shown


def test_a_reflection_that_matched_nothing_leaves_no_supersession_event(tmp_path):
    rig = Rig(tmp_path, [reflection(), correction("price", CORRECTION)])

    rig.prompt(UNRELATED_PROMPT)

    assert not any("superseded" in event for event in rig.logged())


def test_why_lists_each_lesson_once_and_at_most_the_shown_count(tmp_path):
    lessons = [reflection(), correction("price", CORRECTION)]
    rig = Rig(tmp_path, lessons)
    rig.prompt(PRICING_PROMPT)
    rig.prompt(PRICING_PROMPT, session_id="s2")

    found = superseded_sentences(tmp_path / "runs", PROJECT)

    assert len(found) == 1 <= SHOWN
    assert superseded_sentences(tmp_path / "runs", "elsewhere") == []


def test_a_log_line_that_is_not_json_is_named_not_skipped(tmp_path):
    runs = tmp_path / "runs" / "r1"
    runs.mkdir(parents=True)
    (runs / "events.jsonl").write_text("not json\n")

    with pytest.raises(ValueError, match="events.jsonl"):
        superseded_sentences(tmp_path / "runs", PROJECT)
