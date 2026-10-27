import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from symbiont.eval.export_dashboard import (
    ACTIVE_PER_STEP,
    CELLS,
    DashboardInput,
    LaneInput,
    LearnerSnapshot,
    LedgerLine,
    PainPointCount,
    SchemaViolationError,
    ScoreRow,
    TimelineEvent,
    export_dashboard,
)


def _lane(lane_id, role="floor", status="hypothesis", events=None, ledger=None):
    return LaneInput(
        lane_id=lane_id,
        label=lane_id,
        role=role,
        status=status,
        events=events if events is not None else (TimelineEvent(0, "edit", "edit a.py", False),),
        ledger=ledger if ledger is not None else (LedgerLine(0, 100, 0.01),),
    )


def _lanes():
    return (_lane("plain", "floor"), _lane("counters", "reference"), _lane("fly", "under test"))


def _row(key, role, status="hypothesis"):
    return ScoreRow(key=key, label=key, role=role, status=status, value="synthetic")


def _scoreboard():
    return (_row("plain", "floor"), _row("counters", "reference"), _row("fly", "under test"))


def _snapshot(t=0, learned=False):
    return LearnerSnapshot(t, tuple(range(ACTIVE_PER_STEP)), learned)


def _input(**overrides):
    base = DashboardInput(
        act="coding",
        lanes=_lanes(),
        pain_points=(PainPointCount("a.py", 2), PainPointCount("b.py", 5)),
        snapshots=(_snapshot(),),
        scoreboard=_scoreboard(),
        fault_status="hypothesis",
        brain_status="hypothesis",
    )
    return replace(base, **overrides)


def test_scoreboard_includes_counters_row():
    out = export_dashboard(_input())
    by_key = {row["key"]: row for row in out["scoreboard"]}
    assert by_key["counters"]["role"] == "reference"
    assert "fly" in by_key


def test_scoreboard_without_counters_row_fails_the_render():
    rows = tuple(r for r in _scoreboard() if r.key != "counters")
    with pytest.raises(SchemaViolationError, match="counters"):
        export_dashboard(_input(scoreboard=rows))


def test_counters_row_must_sit_directly_beside_the_fly_row():
    rows = (_row("counters", "reference"), _row("plain", "floor"), _row("fly", "under test"))
    with pytest.raises(SchemaViolationError, match="beside"):
        export_dashboard(_input(scoreboard=rows))


def test_counters_row_beside_fly_may_come_before_or_after_it():
    rows = (_row("plain", "floor"), _row("fly", "under test"), _row("counters", "reference"))
    assert [r["key"] for r in export_dashboard(_input(scoreboard=rows))["scoreboard"]][1:] == [
        "fly",
        "counters",
    ]


def test_fly_lane_without_a_counters_lane_is_rejected():
    lanes = (_lane("plain", "floor"), _lane("fly", "under test"))
    with pytest.raises(SchemaViolationError, match="counters lane"):
        export_dashboard(_input(lanes=lanes))


def test_counters_lane_must_sit_directly_beside_the_fly_lane():
    lanes = (_lane("counters", "reference"), _lane("plain", "floor"), _lane("fly", "under test"))
    with pytest.raises(SchemaViolationError, match="beside"):
        export_dashboard(_input(lanes=lanes))


def test_every_lane_and_row_carries_a_known_role():
    rows = _scoreboard() + (_row("x", "winner"),)
    with pytest.raises(SchemaViolationError, match="role"):
        export_dashboard(_input(scoreboard=rows))
    lanes = (_lane("plain", "floor"), _lane("counters", "reference"), _lane("fly", "champion"))
    with pytest.raises(SchemaViolationError, match="role"):
        export_dashboard(_input(lanes=lanes))
    out = export_dashboard(_input())
    roles = {r["role"] for r in out["scoreboard"]} | {lane["role"] for lane in out["lanes"]}
    assert roles <= {"floor", "ceiling", "reference", "under test"}


def test_every_number_carries_a_known_claim_tag():
    bad_row = _scoreboard()[:2] + (_row("fly", "under test", status="proven"),)
    with pytest.raises(SchemaViolationError, match="status"):
        export_dashboard(_input(scoreboard=bad_row))
    bad_lane = (
        _lane("plain"),
        _lane("counters", "reference"),
        _lane("fly", "under test", status=""),
    )
    with pytest.raises(SchemaViolationError, match="status"):
        export_dashboard(_input(lanes=bad_lane))
    with pytest.raises(SchemaViolationError, match="status"):
        export_dashboard(_input(brain_status="measuredish"))
    out = export_dashboard(_input(fault_status="measured", brain_status="established"))
    assert out["panel_status"] == {"fault_map": "measured", "brain": "established"}
    assert {lane["status"] for lane in out["lanes"]} == {"hypothesis"}
    assert {row["status"] for row in out["scoreboard"]} == {"hypothesis"}


def test_timeline_marks_only_repeats():
    events = (
        TimelineEvent(0, "edit", "edit a.py", False),
        TimelineEvent(1, "test", "pytest fails", False),
        TimelineEvent(2, "test", "pytest fails again", True),
        TimelineEvent(3, "edit", "edit b.py", False),
        TimelineEvent(4, "test", "pytest fails again", True),
    )
    lanes = (
        _lane("plain", events=events),
        _lane("counters", "reference"),
        _lane("fly", "under test"),
    )
    snaps = tuple(_snapshot(t) for t in range(5))
    out = export_dashboard(_input(lanes=lanes, snapshots=snaps))
    lane = out["lanes"][0]
    assert lane["repeat_marks"] == [2, 4]
    assert [e["repeat"] for e in lane["events"]] == [False, False, True, False, True]
    assert lane["repeat_count"] == 2


def test_ledger_accumulates_into_fuel_totals():
    ledger = (LedgerLine(0, 100, 0.01), LedgerLine(1, 250, 0.03))
    lanes = (
        _lane("plain", ledger=ledger),
        _lane("counters", "reference"),
        _lane("fly", "under test"),
    )
    out = export_dashboard(_input(lanes=lanes))
    lane = out["lanes"][0]
    assert [p["tokens"] for p in lane["fuel"]] == [100, 350]
    assert lane["totals"] == {"tokens": 350, "dollars": pytest.approx(0.04)}


def test_fault_map_lists_the_most_painful_files_first():
    out = export_dashboard(_input())
    assert [f["path"] for f in out["fault_map"]] == ["b.py", "a.py"]


def test_brain_reports_259_active_of_5177_and_the_learn_flag():
    events = tuple(TimelineEvent(t, "edit", "e", False) for t in range(2))
    lanes = tuple(replace(lane, events=events) for lane in _lanes())
    snaps = (_snapshot(0, False), _snapshot(1, True))
    out = export_dashboard(_input(lanes=lanes, snapshots=snaps))
    assert out["brain"]["cells"] == CELLS == 5177
    assert out["brain"]["active_per_step"] == ACTIVE_PER_STEP == 259
    assert [s["learned"] for s in out["brain"]["steps"]] == [False, True]


def test_brain_snapshot_with_wrong_cell_count_or_index_is_rejected():
    with pytest.raises(SchemaViolationError, match="259"):
        export_dashboard(_input(snapshots=(LearnerSnapshot(0, (1, 2, 3), False),)))
    bad = tuple(range(ACTIVE_PER_STEP - 1)) + (CELLS,)
    with pytest.raises(SchemaViolationError, match="range"):
        export_dashboard(_input(snapshots=(LearnerSnapshot(0, bad, False),)))


def test_brain_shorter_than_the_session_is_rejected_not_padded():
    events = tuple(TimelineEvent(t, "edit", "e", False) for t in range(3))
    lanes = tuple(replace(lane, events=events) for lane in _lanes())
    with pytest.raises(SchemaViolationError, match="snapshots"):
        export_dashboard(_input(lanes=lanes, snapshots=(_snapshot(0),)))


def test_output_never_carries_feature_names_or_scores():
    out = export_dashboard(_input())
    for step in out["brain"]["steps"]:
        assert set(step) == {"t", "active", "learned"}


def test_unknown_act_and_empty_inputs_are_rejected():
    with pytest.raises(SchemaViolationError, match="act"):
        export_dashboard(_input(act="doom"))
    with pytest.raises(SchemaViolationError, match="lanes"):
        export_dashboard(_input(lanes=()))
    with pytest.raises(SchemaViolationError, match="pain"):
        export_dashboard(_input(pain_points=()))


def test_acts_are_freedoom_then_coding():
    from symbiont.eval.export_dashboard import ACTS

    assert ACTS == ("freedoom", "coding")


def test_output_declares_its_schema_version_as_provisional():
    out = export_dashboard(_input())
    assert out["schema"] == "dashboard-v0"
    assert "Task 15" in out["note"]


def test_source_label_passes_through_so_the_page_can_say_where_numbers_came_from():
    out = export_dashboard(_input(source="synthetic replay"))
    assert out["source"] == "synthetic replay"
    assert export_dashboard(_input())["source"] == ""


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"


def _sample_script():
    spec = importlib.util.spec_from_file_location(
        "make_dashboard_sample", ROOT / "scripts" / "make_dashboard_sample.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("act", ["freedoom", "coding"])
def test_shipped_sample_equals_what_the_script_generates(act):
    shipped = (DASHBOARD / "sample" / f"{act}.json").read_text()
    assert shipped == _sample_script().render(act)


@pytest.mark.parametrize("act", ["freedoom", "coding"])
def test_synthetic_sample_is_tagged_hypothesis_and_says_outcomes_are_arbitrary(act):
    doc = json.loads((DASHBOARD / "sample" / f"{act}.json").read_text())
    assert doc["act"] == act
    assert "arbitrary" in doc["source"]
    statuses = {lane["status"] for lane in doc["lanes"]} | {r["status"] for r in doc["scoreboard"]}
    assert statuses | set(doc["panel_status"].values()) == {"hypothesis"}
    assert "ceiling" not in {r["role"] for r in doc["scoreboard"]}


def test_coding_sample_uses_the_spec_arms_and_roles():
    doc = json.loads((DASHBOARD / "sample" / "coding.json").read_text())
    roles = {r["key"]: r["role"] for r in doc["scoreboard"]}
    assert roles == {
        "plain": "floor",
        "counters": "reference",
        "fly": "under test",
        "lora": "under test",
        "wonder": "reference",
    }
    labels = {r["key"]: r["label"] for r in doc["scoreboard"]}
    assert labels["wonder"].startswith("Muse Wonder") and "Route B" in labels["lora"]


def test_dashboard_pages_load_nothing_from_the_network():
    for name in ("index.html", "app.js", "style.css"):
        # the SVG namespace is an identifier, not a request
        text = (DASHBOARD / name).read_text().replace("http://www.w3.org/2000/svg", "")
        assert "http://" not in text and "https://" not in text, name
