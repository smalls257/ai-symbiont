"""First-wrong-step labels from TRAIL and Who&When: readers, labels, tallies and the warner check.

Every trace and row here is synthetic and hand-written in the datasets' shapes; no dataset text.
"""

import importlib
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pytest

from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
MODULES = ("annotated", "trail_reader", "who_when_reader", "tallies", "warner_check", "warner_fit")


@pytest.fixture
def fws(monkeypatch):
    """The fws script modules, imported fresh with their directories on the path."""
    monkeypatch.syspath_prepend(str(SCRIPTS / "routea"))
    monkeypatch.syspath_prepend(str(SCRIPTS / "fws"))
    for name in MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    return {name: importlib.import_module(name) for name in MODULES}


def span(span_id, name, ts="2025-01-01T00:00:00", children=(), kind="CHAIN", status="Ok"):
    return {
        "span_id": span_id,
        "span_name": name,
        "timestamp": ts,
        "status_code": status,
        "span_attributes": {"openinference.span.kind": kind, "output.value": "observed"},
        "child_spans": list(children),
    }


def trail_trace():
    """A manager CodeAgent with three steps; step 2 runs a managed agent with one step."""
    managed = span(
        "m1",
        "ToolCallingAgent.run",
        "T02.5",
        [span("ms1", "Step 1", "T02.6", [span("ml1", "LiteLLMModel.__call__", kind="LLM")])],
        kind="AGENT",
    )
    steps = [
        span("s3", "Step 3", "T03", [span("f", "FinalAnswerTool", kind="TOOL")]),
        span("s1", "Step 1", "T01", [span("l1", "LiteLLMModel.__call__", kind="LLM")]),
        span(
            "s2",
            "Step 2",
            "T02",
            [span("l2", "LiteLLMModel.__call__", kind="LLM"), managed],
            status="Error",
        ),
    ]
    root = span("r", "CodeAgent.run", "T00", steps, kind="AGENT")
    return {"trace_id": "abc", "spans": [span("top", "main", "T00", [root])]}


def annotation(*locations):
    return {"trace_id": "abc", "errors": [{"location": loc} for loc in locations], "scores": []}


def test_trail_steps_follow_start_time_and_errors_land_on_the_innermost_step(fws):
    trace = fws["trail_reader"].trace_from(
        trail_trace(), annotation("ml1", "l2", "nowhere"), "gaia"
    )
    kinds = [r.kind for r in trace.records]
    assert kinds == [Kind.USER_TURN, Kind.COMMAND, Kind.COMMAND, Kind.COMMAND, Kind.AGENT_TURN]
    assert [r.exit_code for r in trace.records[1:4]] == [0, 1, 0]
    assert trace.records[3].command is None  # the managed agent's step called no tool
    assert trace.error_steps == (2, 3) and trace.first_wrong == 2
    assert trace.unplaced_errors == 1


def test_a_trail_annotation_for_another_trace_is_refused(fws):
    other = annotation("l1") | {"trace_id": "zzz"}
    with pytest.raises(ValueError, match="paired with trace abc"):
        fws["trail_reader"].trace_from(trail_trace(), other, "swe_bench")


@pytest.mark.periphery
def test_read_trail_counts_bad_files_and_pairs_unnamed_annotations_by_file_name(fws, tmp_path):
    for trace_dir, annotation_dir, _ in fws["trail_reader"].SPLITS.values():
        (tmp_path / trace_dir).mkdir(parents=True)
        (tmp_path / annotation_dir).mkdir(parents=True)
    swe, swe_notes, _ = fws["trail_reader"].SPLITS["swe_bench"]
    (tmp_path / swe / "abc.json").write_text(json.dumps(trail_trace()))
    unnamed = {k: v for k, v in annotation("l1").items() if k != "trace_id"}
    (tmp_path / swe_notes / "abc.json").write_text(json.dumps(unnamed))
    gaia, gaia_notes, _ = fws["trail_reader"].SPLITS["gaia"]
    (tmp_path / gaia / "abc.json").write_text(json.dumps(trail_trace()))
    (tmp_path / gaia_notes / "abc.json").write_text('{"errors": [1,]}')
    read = fws["trail_reader"].read_trail(tmp_path)
    assert [t.split for t in read.traces] == ["swe_bench"]
    assert read.traces[0].first_wrong == 1
    assert read.paired_by_file_name == 1
    assert len(read.unreadable) == 1 and "not json" in read.unreadable[0].reason
    assert read.annotations_without_trace == 0
    (tmp_path / swe_notes / "orphan.json").write_text(json.dumps(annotation()))
    assert fws["trail_reader"].read_trail(tmp_path).annotations_without_trace == 1


def who_row(mistake_step="2", agent="Orchestrator"):
    history = [
        {"content": "please find it", "role": "human"},
        {"content": "plan ```python\nprint(1)\n```", "role": "Orchestrator (thought)"},
        {"content": "exitcode: 1 (execution failed)", "role": "ComputerTerminal"},
        {"content": "try again", "role": "Orchestrator (-> WebSurfer)"},
    ]
    return {
        "history": history,
        "question_ID": "q1",
        "mistake_step": mistake_step,
        "mistake_agent": agent,
    }


def test_who_when_terminal_output_is_the_command_the_previous_message_wrote(fws):
    check = fws["who_when_reader"].trace_from_row(who_row(), "hand_crafted")
    records = check.trace.records
    assert [r.kind for r in records] == [
        Kind.USER_TURN,
        Kind.AGENT_TURN,
        Kind.COMMAND,
        Kind.AGENT_TURN,
    ]
    assert (records[2].command, records[2].exit_code) == ("python", 1)
    assert check.trace.first_wrong == 2 and check.agent_matches is False


def test_who_when_blame_matches_an_agent_whatever_its_role_suffix(fws):
    check = fws["who_when_reader"].trace_from_row(who_row("3", "orchestrator"), "hand_crafted")
    assert check.agent_matches is True


def test_who_when_blamed_step_outside_the_history_is_counted_not_guessed(fws):
    check = fws["who_when_reader"].trace_from_row(who_row("9"), "hand_crafted")
    assert check.trace.first_wrong is None and check.trace.unplaced_errors == 1
    assert check.agent_matches is None


@pytest.mark.periphery
def test_read_who_when_refuses_a_repeated_question_id(fws, tmp_path):
    for name, _ in fws["who_when_reader"].SPLITS.values():
        target = str(tmp_path / name)
        duckdb.sql(
            "copy (select [{'content': 'x', 'role': 'human'}] as history, 'q1' as question_ID, "
            f"'0' as mistake_step, 'human' as mistake_agent from range(2)) to '{target}' "
            "(format parquet)"
        )
    with pytest.raises(ValueError, match="question id repeats"):
        fws["who_when_reader"].read_who_when(tmp_path)


@pytest.mark.periphery
def test_read_who_when_names_the_file_and_row_of_a_malformed_row(fws, tmp_path):
    for name, _ in fws["who_when_reader"].SPLITS.values():
        target = str(tmp_path / name)
        duckdb.sql(
            "copy (select [{'content': 'x', 'role': 'human'}] as history, 'q' || range as "
            "question_ID, case when range = 1 then 'two' else '0' end as mistake_step, "
            f"'human' as mistake_agent from range(2)) to '{target}' (format parquet)"
        )
    with pytest.raises(ReadError) as caught:
        fws["who_when_reader"].read_who_when(tmp_path)
    assert caught.value.path.name == "Algorithm-Generated.parquet"
    assert caught.value.line_no == 2


def test_who_when_row_without_a_history_is_a_key_error_the_reader_wraps(fws):
    with pytest.raises(KeyError):
        fws["who_when_reader"].trace_from_row({"question_ID": "q"}, "hand_crafted")


def labeled(fws, mistake_step="2"):
    trace = fws["who_when_reader"].trace_from_row(who_row(mistake_step), "hand_crafted").trace
    return trace, fws["annotated"].step_labels(trace, window=2)


def test_step_labels_mark_the_first_wrong_step_and_the_window_before_it(fws):
    _, labels = labeled(fws)
    assert labels.at_first_wrong.tolist() == [False, False, True, False]
    assert labels.first_wrong_ahead.tolist() == [True, True, False, False]
    assert labels.mined_trouble_here.tolist() == [False, False, True, False]
    assert labels.boundary.tolist() == [False, False, True, False]


def test_step_labels_refuse_steps_out_of_order(fws):
    trace, _ = labeled(fws)
    shuffled = type(trace)(**{**trace.__dict__, "records": trace.records[::-1]})
    with pytest.raises(ValueError, match="not numbered"):
        fws["annotated"].step_labels(shuffled)


def test_tallies_see_mined_trouble_at_the_first_wrong_step(fws):
    trace, labels = labeled(fws)
    around = fws["tallies"].around_first_wrong([trace], [labels], window=2)
    assert around["first_wrong_is_boundary"] == 1
    assert around["mined_trouble_at_first_wrong"] == 1
    assert around["mined_trouble_within_window_after"] == 0
    agreement = fws["tallies"].agreement([labels])
    assert agreement["both"] == 2 and agreement["cohen_kappa"] == 1.0


def test_cohen_kappa_is_zero_at_chance_and_none_when_undefined(fws):
    assert fws["tallies"].cohen_kappa(25, 25, 25, 25) == 0.0
    assert fws["tallies"].cohen_kappa(0, 0, 0, 10) is None
    # 20 yes-yes, 5 + 10 disagreements, 15 no-no: observed 0.7, chance 0.5, kappa 0.4.
    assert fws["tallies"].cohen_kappa(20, 5, 10, 15) == 0.4


def table(fws, risks, truth, boundary=None, session=None):
    n = len(risks)
    return fws["warner_check"].StepTable(
        risks=np.asarray(risks, dtype=float),
        boundary=np.ones(n, dtype=bool) if boundary is None else np.asarray(boundary),
        session=np.zeros(n, dtype=int) if session is None else np.asarray(session),
        position=np.arange(n),
        labels={"wrong": np.asarray(truth, dtype=bool)},
    )


def test_label_scores_rank_spend_notes_and_print_the_floor(fws):
    scores = fws["warner_check"].label_scores(
        table(fws, [0.1, 0.9, 0.2, 0.8], [False, True, False, False]), "wrong", note_at=0.5
    )
    assert scores["auc"] == 1.0
    assert scores["operating_point"] == {"notes": 1, "right_notes": 1, "precision": 1.0}
    assert scores["risk_at_or_above_note_at"]["steps"] == 2
    assert scores["floor_every_boundary_precision"] == 0.25
    assert scores["auc_step_position_reference"] == pytest.approx(1 / 3, abs=1e-4)


def test_a_label_with_no_positive_has_no_auc_never_a_half(fws):
    scores = fws["warner_check"].label_scores(table(fws, [0.1, 0.9], [False, False]), "wrong", 0.5)
    assert scores["auc"] is None
    assert scores["auc_ci95"]["low"] is None
    assert scores["operating_point"]["precision"] == 0.0


def test_bootstrap_resamples_whole_traces(fws):
    steps = table(fws, [0.1, 0.9, 0.2, 0.8], [False, True, False, True], session=[0, 0, 1, 1])
    interval = fws["warner_check"].bootstrap_auc(steps, steps.labels["wrong"])
    assert interval == {"low": 1.0, "high": 1.0, "undefined_draws": 0}
