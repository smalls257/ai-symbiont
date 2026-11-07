"""The Inbox gets the story lines: the goal leads, old cards fall back to their sentences."""

from dataclasses import replace

from story_builders import owners_lesson
from symbiont.core.notes import NOTE_CHARS, story_note
from symbiont.miner.incident_types import Incident, Outcome
from symbiont.miner.painpoint import Signal
from symbiont.service.incident_view import IncidentContext, incident_groups

DAYS = {"s1": "2026-10-01"}


def card(**over):
    base = Incident(
        session_id="s1", step=1, signal=Signal.FAILED_COMMAND,
        what_happened="The agent ran pytest and it failed.", first_wrong="", cost_steps=0,
        what_fixed_it="Fixed by editing a.py.", outcome=Outcome.FIXED_IN_CODE, noise=None,
        topic="", files=(), situation=("running", "pytest", ""), fingerprint="failure:pytest:E",
        example="pytest", working_on="asked words", broke="`pytest` failed: boom",
        ended="fixed by editing a.py",
    )  # fmt: skip
    return replace(base, **over)


def test_the_session_goal_beats_the_asked_words_and_the_lines_reach_group_and_card():
    context = IncidentContext(goals={"s1": "moving the domains"})
    (group,) = incident_groups([card()], DAYS, context)["groups"]
    assert (group["workingOn"], group["broke"], group["ended"]) == (
        "moving the domains", "`pytest` failed: boom", "fixed by editing a.py",
    )  # fmt: skip
    assert group["cards"][0]["workingOn"] == "moving the domains"
    (plain,) = incident_groups([card()], DAYS)["groups"]
    assert plain["workingOn"] == "asked words"


def test_a_card_stored_before_the_story_falls_back_to_its_sentences():
    old = card(working_on="", broke="", ended="")
    (group,) = incident_groups([old], DAYS)["groups"]
    assert group["broke"] == "The agent ran pytest and it failed."
    assert group["ended"] == "Fixed by editing a.py." and group["workingOn"] == ""


def test_the_note_to_the_agent_is_at_most_300_characters_and_has_no_labels():
    lesson = replace(owners_lesson(), asked="moving the domains", fix_added="")
    note = story_note(lesson)
    assert len(note) <= NOTE_CHARS and note.startswith("While moving the domains: ")
    crowded = story_note(replace(lesson, asked="word " * 100))
    assert len(crowded) <= NOTE_CHARS and crowded.startswith("While word")
    assert "Last time: fixed by editing identity.controller.ts" in note
    assert "What broke" not in note and "Working on" not in note
    quiet = story_note(replace(lesson, asked="", agent_intent=""))
    assert quiet.startswith("`pnpm api:generate` failed")
