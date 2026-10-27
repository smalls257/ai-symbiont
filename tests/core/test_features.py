import numpy as np
import pytest

from record_builders import edit, replace_text, run, session, view
from symbiont.core.features import (
    COUNTER_FEATURES,
    FEATURE_NAMES,
    N_FEATURES,
    featurise,
    scratch_files,
)
from symbiont.core.slot import Situation
from symbiont.miner.painpoint import PainPoint, Signal, Signature


def situation(records, history=()):
    return Situation(
        project="tobymao/sqlglot",
        session_prefix=tuple(session(*records)),
        history=tuple(history),
        candidates=(),
    )


def pain(signal, key, step=0, session_id="s0"):
    return PainPoint(Signature(signal, key), session_id, step, ((session_id, step),))


def named(x, prefix):
    return {n: v for n, v in zip(FEATURE_NAMES, x, strict=True) if n.startswith(prefix)}


def test_feature_shape_86():
    x = featurise(situation([run("pytest tests/test_a.py", 1)]))
    assert N_FEATURES == 86
    assert x.shape == (86,)
    assert x.dtype == np.float32


def test_features_deterministic():
    s = situation([view("a.py"), run("python -m pytest tests/test_a.py -q", 1)])
    assert np.array_equal(featurise(s), featurise(s))


def test_command_token_bag_is_stable_across_processes():
    # Python's built-in hash() is salted per process; a salted bag would give a
    # dashboard and a trained learner different inputs for the same command.
    x = named(featurise(situation([run("pytest", 1)])), "token_")
    assert [k for k, v in x.items() if v] == ["token_8"]


def test_feature_names_cover_86():
    assert len(FEATURE_NAMES) == 86
    assert len(set(FEATURE_NAMES)) == 86


def test_empty_prefix_is_all_zero():
    assert not featurise(situation([])).any()


def test_position_is_one_hot_and_moves_with_the_step():
    early = named(featurise(situation([run("ls")])), "position_")
    late = named(featurise(situation([run("ls")] * 30)), "position_")
    assert sum(early.values()) == 1 and sum(late.values()) == 1
    assert early != late


def test_file_history_counts_prior_touches_of_the_current_file():
    base = [view("a.py"), edit("a.py"), edit("b.py")]
    fresh = named(featurise(situation([*base, edit("c.py")])), "file_")
    again = named(featurise(situation([*base, edit("a.py")])), "file_")
    assert fresh["file_edits_0"] == 1.0 and fresh["file_reads_0"] == 1.0
    assert fresh != again
    assert again["file_edits_1"] == 1.0 and again["file_reads_1"] == 1.0


def test_file_history_is_silent_when_the_step_names_no_file():
    assert sum(named(featurise(situation([edit("a.py"), run("ls")])), "file_").values()) == 0


def test_lines_added_is_log_scaled_per_step_and_per_session():
    small = edit("a.py", diff="--- a/a.py\n+++ b/a.py\n-x\n+y\n")
    big = edit("a.py", diff="+++ b/a.py\n" + "+line\n" * 50)
    x = named(featurise(situation([small, big])), "lines_added_")
    assert x["lines_added_step"] == pytest.approx(np.log1p(50))
    assert x["lines_added_session"] == pytest.approx(np.log1p(51))


def test_outcome_trail_marks_recent_failures_newest_first():
    x = named(featurise(situation([run("a", 0), run("b", 1), run("c", 0)])), "trail_")
    assert [x[f"trail_{i}"] for i in range(3)] == [0.0, 1.0, 0.0]
    x = named(featurise(situation([run("a", 0), run("b", 0), run("c", 2)])), "trail_")
    assert x["trail_0"] == 1.0


def test_signal_history_separates_signals():
    records = [run("pytest tests/test_a.py", 1)]
    loop = featurise(situation(records, [pain(Signal.LOOP, ("pytest", "t"))]))
    fail = featurise(situation(records, [pain(Signal.FAILED_COMMAND, ("pytest", "t"))]))
    assert not np.array_equal(loop, fail)


def test_pain_points_from_the_future_of_this_session_are_ignored():
    records = [run("ls"), run("ls")]
    future = pain(Signal.LOOP, ("ls", "-"), step=50, session_id="s1")
    assert np.array_equal(featurise(situation(records, [future])), featurise(situation(records)))


def test_hub_modules_carry_no_blast_radius_history():
    records = [edit("sqlglot/dialects/duckdb.py")]
    hub_hit = pain(Signal.BLAST_RADIUS, ("sqlglot/dialects/duckdb.py", "sqlglot/__init__.py"))
    other_hit = pain(Signal.BLAST_RADIUS, ("sqlglot/dialects/duckdb.py", "sqlglot/parser.py"))
    plain = featurise(situation(records))
    hubs = frozenset({"sqlglot/__init__.py"})
    assert np.array_equal(featurise(situation(records, [hub_hit]), hubs=hubs), plain)
    assert not np.array_equal(featurise(situation(records, [other_hit]), hubs=hubs), plain)
    assert not np.array_equal(featurise(situation(records, [hub_hit])), plain)


def test_rework_of_a_scratch_file_the_session_created_is_not_a_mistake():
    created = edit("reproduce.py", diff="--- /dev/null\n+++ b/reproduce.py\n+print(1)\n")
    redo = replace_text("reproduce.py", "print(1)", "print(2)")
    records = [created, redo, run("python reproduce.py")]
    prefix = session(*records)
    rework = pain(Signal.REWORKED_EDIT, ("reproduce.py",), step=1, session_id="s1")
    other = pain(Signal.REWORKED_EDIT, ("sqlglot/parser.py",), step=1, session_id="s1")
    plain = featurise(situation(records))
    assert scratch_files(prefix) == frozenset({("s1", "reproduce.py")})
    assert np.array_equal(featurise(situation(records, [rework])), plain)
    assert not np.array_equal(featurise(situation(records, [other])), plain)


def test_scratch_files_of_earlier_sessions_can_be_supplied():
    records = [run("ls")]
    rework = pain(Signal.REWORKED_EDIT, ("reproduce.py",), session_id="s0")
    plain = featurise(situation(records))
    assert not np.array_equal(featurise(situation(records, [rework])), plain)
    scratch = frozenset({("s0", "reproduce.py")})
    assert np.array_equal(featurise(situation(records, [rework]), scratch=scratch), plain)


def test_counters_read_only_position_file_history_lines_added_and_edit_kind():
    names = {FEATURE_NAMES[i] for i in COUNTER_FEATURES}
    prefixes = ("position_", "file_", "lines_added_", "action_")
    assert names and all(n.startswith(prefixes) for n in names)
    assert "action_edit" in names


def test_pain_point_at_the_current_step_is_not_history():
    # The pain point mined at this very step is the label a learner predicts.
    records = [run("ls"), run("pytest tests/test_a.py", 1)]
    now = session(*records)[-1].step
    here = pain(Signal.FAILED_COMMAND, ("pytest", "tests/test_a.py"), step=now, session_id="s1")
    before = pain(
        Signal.FAILED_COMMAND, ("pytest", "tests/test_a.py"), step=now - 1, session_id="s1"
    )
    plain = featurise(situation(records))
    assert np.array_equal(featurise(situation(records, [here])), plain)
    assert not np.array_equal(featurise(situation(records, [before])), plain)


def test_blast_radius_history_survives_when_the_edited_path_is_a_hub():
    records = [edit("sqlglot/__init__.py")]
    hit = pain(Signal.BLAST_RADIUS, ("sqlglot/__init__.py", "sqlglot/parser.py"))
    plain = featurise(situation(records))
    hubs = frozenset({"sqlglot/__init__.py"})
    assert not np.array_equal(featurise(situation(records, [hit]), hubs=hubs), plain)
