"""The session page: tags from the (session, step) join, picker ranking, filters, caps and refusals.

Violation prevented: Silent Fallback (a failed or missing session drawn as an empty page, a card
with no step quietly tagged as grouped) and Leaky Narrative (a command running as markup).
The model and renderer run under node with a fake pane and a fake fetch.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from symbiont.miner.incident_types import Incident, NoiseReason, Outcome
from symbiont.miner.painpoint import Signal
from symbiont.miner.session_summary import SessionSummary, SummaryOutcome
from symbiont.service.incident_view import incident_groups
from symbiont.service.topic_view import _session

HERE = Path(__file__).parent
STATIC = HERE.parents[1] / "src" / "symbiont" / "service" / "static"
HOSTILE = "<img src=x onerror"


def _incident(session, step, program="pytest", noise=None):
    return Incident(
        session_id=session, step=step, signal=Signal.FAILED_COMMAND,
        what_happened=f"The agent ran {program} and it failed.", first_wrong="", cost_steps=0,
        what_fixed_it="Edited app.py, then the command passed.", outcome=Outcome.FIXED_IN_CODE,
        noise=noise, topic="Parser work", files=("app.py",), situation=("running", program, "x"),
        fingerprint=f"failure:{program}:boom", example=f"{program} tests",
    )  # fmt: skip


def real_snapshot():
    """The snapshot keys the page reads, built by the production emitters, not by hand."""
    days = {"s1": "2026-03-09", "s2": "2026-03-10"}
    cards = [
        _incident("s1", 3),
        _incident("s1", 5),
        _incident("s2", 1),
        _incident("s1", 7, program="ls", noise=NoiseReason.LOOK_AROUND),
    ]
    summary = SessionSummary(
        "s1", "Fix parser", SummaryOutcome.DONE, "Imports kept breaking.", False
    )
    listed = _session(summary, {})
    listed["date"] = days["s1"]
    topics = [{"key": "t1", "name": "Parser work", "sessionList": [listed]}]
    return {"incidents": incident_groups(cards, days), "topicView": {"topics": topics}}


def test_every_real_card_carries_the_step_the_join_needs():
    for group in real_snapshot()["incidents"]["groups"]:
        for card in group["cards"]:
            assert isinstance(card["step"], int) and card["sessionId"]


@pytest.fixture(scope="module")
def drawn(tmp_path_factory):
    snapshot = tmp_path_factory.mktemp("snap") / "snapshot.json"
    snapshot.write_text(json.dumps(real_snapshot()), encoding="utf-8")
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "session_harness.js"), str(STATIC), str(snapshot)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_the_page_registers_itself_as_the_session_detail_view(drawn):
    assert drawn["registered"] == "session"


def test_a_step_joins_its_card_by_session_and_step(drawn):
    kinds = [t["kind"] for t in drawn["tags"]]

    assert kinds == ["group", "noise", "none", "group", "none"]
    assert drawn["tags"][0]["name"] == "pytest failing with boom"
    assert (
        drawn["tags"][1]["reason"]
        == "the agent was feeling its way around with a read-only command"
    )


def test_cards_without_a_step_do_not_tag_anything(drawn):
    assert drawn["tags"][4]["kind"] == "none"
    assert drawn["stepless"] == 0


def test_the_picker_ranks_sessions_by_grouped_cards_and_leaves_noise_out(drawn):
    rows = drawn["picker"]["rows"]

    assert [r["hits"] for r in rows] == sorted((r["hits"] for r in rows), reverse=True)
    assert "s2" in [r["id"] for r in rows] and "n1" not in json.dumps(rows)
    assert {r["id"]: r["hits"] for r in rows}["s1"] == 2
    assert drawn["picker"]["currentListed"] is True
    assert next(r for r in rows if r["id"] == "s1")["goal"] == "Fix parser"


def test_the_picker_keeps_forty_and_flags_a_session_it_does_not_list(drawn):
    assert drawn["capped40"] == 40
    assert drawn["pickerOther"] is False


def test_the_message_filter_keeps_only_grouped_ones(drawn):
    assert drawn["keptMessages"] == [3]
    assert drawn["keptAll"] == 2


def test_hide_noise_drops_folded_failures_and_counts_them(drawn):
    assert drawn["keptFailed"] == [3, 4]
    assert drawn["noise"] == 1


def test_a_capped_session_says_n_of_m_steps_and_a_whole_one_says_nothing(drawn):
    assert "Showing 600 of 5,000 steps" in drawn["capText"]
    assert drawn["capNone"] == ""
    assert "Showing 600 of 5,000 steps" in drawn["html"]
    assert "Showing" not in drawn["small"].split("Step by step")[1].split("</p>")[0]


def test_the_header_names_the_session_and_its_counts(drawn):
    html = drawn["html"]

    assert "Fix the parser" in html and "Mar 9, 2026" in html and "41 min" in html
    assert "Imports kept breaking." in html and "Sessions with the most grouped trouble" in html
    assert "failed commands (1 noise)" in html and "5,000" in html and "Topic: Parser work" in html
    assert drawn["wall"] == ["41 min", "2 h", None]


def test_it_shows_loading_then_fetches_the_session_once_with_the_project_and_id(drawn):
    assert "Loading" in drawn["loading"]
    assert drawn["url"] == "/dashboard/session?project=my%20repo&id=s1"


def test_each_failed_command_carries_its_tag(drawn):
    html = drawn["html"]

    assert "$ pytest tests/x" in html and "In group: <a data-route" in html
    assert (
        "Noise: the agent was feeling its way around with a read-only command" in html
        and "Not in a group" in html
    )


def test_a_focus_step_draws_the_dashed_line_and_one_outside_the_steps_says_so(drawn):
    assert 'class="focus"' in drawn["html"]
    assert 'class="focus"' not in drawn["outside"]
    assert "Step 4000 is not among the steps shown" in drawn["outside"]


def test_the_filters_redraw_the_lists(drawn):
    messages = drawn["afterGroupFilter"].split("Failed commands")[0].split("Your messages")[1]
    assert "please fix it" not in messages
    assert "ls</div>" not in drawn["afterQuiet"]


def test_the_picker_navigates_to_the_chosen_session(drawn):
    assert drawn["navigated"] == [{"view": "session", "id": "s2"}]


def test_the_crumb_names_the_session_date(drawn):
    assert "Session Mar 9, 2026" in drawn["crumbs"]


def test_an_unknown_id_and_an_unreadable_log_are_told_apart_with_a_way_back(drawn):
    assert "No such session." in drawn["missing"] and "Back to the inbox" in drawn["missing"]
    assert "no longer readable" in drawn["gone"] and "Back to the inbox" in drawn["gone"]


def test_a_refusal_or_a_network_error_shows_the_error_not_an_empty_page(drawn):
    assert "unknown project" in drawn["refused"]
    assert "Could not load this session: connection refused" in drawn["down"]


def test_log_text_never_runs_as_markup(drawn):
    for key in ("html", "afterGroupFilter", "afterQuiet"):
        assert HOSTILE not in drawn[key]
    assert "&lt;img src=x onerror" in drawn["html"]


def test_every_real_card_joins_to_a_group_or_noise(drawn):
    assert drawn["joined"] == drawn["cardCount"] == 4
    assert drawn["stepless"] == 0


def test_a_summarized_session_shows_its_outcome_and_friction(drawn):
    assert "ended" in drawn["html"] and ">done<" in drawn["html"]
    assert "Imports kept breaking." in drawn["html"]


def test_an_unsummarized_session_shows_no_chip_and_no_friction(drawn):
    html = drawn["unsummarized"]

    assert "Fix the parser" in html and "ended" not in html and 'class="fr"' not in html


def test_a_404_that_is_not_json_is_its_own_error(drawn):
    assert "service answered 404" in drawn["plainNotFound"]
    assert "no longer readable" not in drawn["plainNotFound"]


def test_an_unknown_lane_is_not_drawn_and_odd_minutes_are_left_out(drawn):
    assert "undefined" not in drawn["oddLane"] and "NaN" not in drawn["oddLane"]
    assert "wall clock" not in drawn["oddLane"]
