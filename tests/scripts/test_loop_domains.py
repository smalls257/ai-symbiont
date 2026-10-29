"""The real domain plugins' contracts on synthetic inputs: no Glimmer, no Docker, no ViZDoom."""

import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(autouse=True)
def loop_on_path(monkeypatch):
    for name in ("loop", "routeb", "act1", "calibration"):
        monkeypatch.syspath_prepend(str(SCRIPTS / name))
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def mod(name):
    return importlib.import_module(name)


# -- coding-sqlglot -------------------------------------------------------------------------------


def coding(tmp_path, held=("t3",)):
    cs = mod("coding_sqlglot")
    (tmp_path / "data").mkdir()
    pool = {"pool": [{"instance_id": f"t{n}"} for n in range(6)]}
    (tmp_path / "data" / "pool.json").write_text(json.dumps(pool))
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"evaluation": [{"task": t} for t in held]}))
    runner = mod("runner").PrintingRunner(say=lambda _line: None)
    return cs.CodingSqlglot(cs.CodingPaths(tmp_path, split, tmp_path / "clone"), runner)


def test_training_batches_never_hold_a_held_out_task(tmp_path):
    domain = coding(tmp_path)
    assert domain.held_out() == frozenset({"t3"})
    for index in range(4):
        assert "t3" not in domain.training_batch(index)


def test_a_rounds_model_goes_to_cal2_by_name_and_plain_needs_no_flag(tmp_path):
    cs = mod("coding_sqlglot")
    paths = cs.CodingPaths(tmp_path, tmp_path / "s", tmp_path / "c")
    personal = cs.cal2_command(paths, "Muse-Glimmer-30B-coding-sqlglot-r1", "loop/x", None)
    assert personal[personal.index("--model") + 1] == "Muse-Glimmer-30B-coding-sqlglot-r1"
    assert personal[personal.index("--fixed-runs") + 1] == "1"
    assert "--model" not in cs.cal2_command(paths, cs.PLAIN_GLIMMER, "loop/x", None)


def test_an_attempt_without_a_graded_record_is_ungraded_never_failed(tmp_path):
    cs, at = mod("coding_sqlglot"), mod("attempts")
    log = tmp_path / "loop" / "r0"
    log.mkdir(parents=True)
    rows = [
        {"instance_id": "t1", "stage": "fixed", "run": 1, "reasoning": "low", "resolved": True},
        {"instance_id": "t2", "stage": "fixed", "run": 1, "reasoning": "low", "resolved": None},
    ]
    (log / "calibration.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    found = cs.attempts_from_log(log, "loop/r0", ["t1", "t2"], "m",
                                 (0, at.Split.TRAINING, frozenset()))  # fmt: skip
    assert [str(a.outcome) for a in found] == ["passed", "ungraded"]
    assert found[0].attempt_id == "loop/r0/fixed-run1-low/t1"
    assert cs.attempt_log(found[0]) == "loop/r0"
    with pytest.raises(FileNotFoundError):
        cs.attempts_from_log(tmp_path / "none", "x", ["t1"], "m", (0, at.Split.TRAINING, set()))


def plain_run(**facts):
    runs, sr = mod("general_runs"), mod("sqlglot_runs")
    base = dict(instance_id="t1", run_id="loop/r0/fixed-run1-low", resolved=False, step_limit=50,
                steps=50, first_view={"sqlglot/parser.py": 4}, rereads={}, first_edit=None,
                edited=(), scratch_scripts=0, verified_test=None, traps=())  # fmt: skip
    return runs.PlainRun("t1", "loop/r0", 50, False, "LimitsExceeded", False,
                         sr.RunFacts(**(base | facts)), ())  # fmt: skip


def test_habit_marks_read_the_situation_and_the_mistake_from_the_run():
    cs, ut = mod("coding_sqlglot"), mod("utility")
    gold = {"t1": ("sqlglot/parser.py",)}
    mark = cs._habit_mark
    assert mark("habit-edit-once-found", plain_run(), gold) is ut.Mark.REPEATED
    edited = plain_run(first_edit=9, edited=("sqlglot/parser.py",))
    assert mark("habit-edit-once-found", edited, gold) is ut.Mark.AVOIDED
    assert mark("habit-check-the-layer", plain_run(), gold) is ut.Mark.NOT_APPLICABLE
    wrong = plain_run(first_edit=9, edited=("sqlglot/generator.py",))
    assert mark("habit-check-the-layer", wrong, gold) is ut.Mark.REPEATED


def test_route_a_arms_are_refused_by_the_cal2_driver(tmp_path):
    domain = coding(tmp_path)
    with pytest.raises(mod("learners").RouteNotWiredError):
        domain.attempt("user-model+symbiont-coding-sqlglot-r1", ["t1"], 0, frozenset())


# -- freedoom -------------------------------------------------------------------------------------


def freedoom(tmp_path, prereg=None):
    fd = mod("freedoom")
    runner = mod("runner").PrintingRunner(say=lambda _line: None)
    return fd.Freedoom(fd.FreedoomPaths(tmp_path, tmp_path / "episodes", prereg), runner)


def test_freedoom_trains_on_new_seeds_of_training_levels_and_holds_out_map04_and_map08(tmp_path):
    domain = freedoom(tmp_path)
    assert domain.held_out() == frozenset({"MAP04/s3", "MAP04/s4", "MAP08/s3", "MAP08/s4"})
    first, second = domain.training_batch(0), domain.training_batch(1)
    assert not set(first) & set(second)
    assert not {t.split("/")[0] for t in first + second} & {"MAP04", "MAP08", "MAP12"}


def test_freedoom_evaluation_refuses_without_a_frozen_prereg(tmp_path):
    with pytest.raises(RuntimeError, match="prereg"):
        freedoom(tmp_path).evaluate("Muse-Glimmer-30B-freedoom-r1", 0, frozenset())


def test_a_missing_episode_is_ungraded_and_play_goes_to_the_collector_by_model_name(tmp_path):
    domain = freedoom(tmp_path)
    found = domain.attempt("Muse-Glimmer-30B-freedoom-r1", ["MAP01/s1", "MAP02/s1"], 0, set())
    assert {str(a.outcome) for a in found} == {"ungraded"}
    (argv,) = domain.runner.commands
    assert argv[argv.index("--glimmer-model") + 1] == "Muse-Glimmer-30B-freedoom-r1"
    assert argv[argv.index("--levels") + 1] == "MAP01,MAP02"


def test_freedoom_cards_pool_by_check_and_marks_follow_the_moves_played(tmp_path):
    fd, ut, gl = mod("freedoom"), mod("utility"), mod("symbiont.act1.game_lessons")
    pain = mod("symbiont.act1.game_pains").GamePain.WASTED_MOVE

    def lesson(session, room):
        return gl.GameLesson(f"{session}/wasted_move/{room}/go_to(key)", session, "MAP01", 3,
                             pain, 2, f"`go_to(key)` changed nothing in {room}.",
                             "Go_to(exit) took you on.", "Check the key is listed.")  # fmt: skip

    assert fd.card_id(lesson("a", "start room")) == fd.card_id(lesson("b", "third room"))
    key = fd.card_id(lesson("a", "start room"))
    assert key.startswith("freedoom/wasted_move/go_to/")
    card = fd._card(key, [lesson("a", "start room")], None, 0)
    assert str(card.resolution.source) == "engine-observed progress"
    attempt = mod("attempts").Attempt("r0/x.jsonl", "MAP01/s1", 0, "m",
                                      mod("attempts").Split.TRAINING,
                                      mod("attempts").Outcome.FAILED)  # fmt: skip
    domain = freedoom(tmp_path)
    domain.steps["r0/x.jsonl"] = [("go_to", frozenset({"wasted_move"})), ("turn", frozenset())]
    assert domain.mark(card, attempt) is ut.Mark.REPEATED
    domain.steps["r0/x.jsonl"] = [("turn", frozenset({"wasted_move"}))]
    assert domain.mark(card, attempt) is ut.Mark.NOT_APPLICABLE


def test_a_text_naming_a_held_out_level_is_a_leak(tmp_path):
    hits = freedoom(tmp_path).leak_hits({"a": "Seen in MAP04 near the door.", "b": "MAP05 too."})
    assert hits == {"a": ["MAP04"]}
