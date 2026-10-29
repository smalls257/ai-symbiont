"""Plug scored-run decisions on hand-written gains, rates and answers."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
SCRIPT_DIRS = {ROUTEA, ROUTEA.parent / "aidev"}


@pytest.fixture(autouse=True)
def forget_script_modules():
    """Drop only modules loaded from scripts/; shared libraries stay loaded."""
    yield
    for name, module in list(sys.modules.items()):
        if Path(getattr(module, "__file__", None) or "/").parent in SCRIPT_DIRS:
            del sys.modules[name]


@pytest.fixture
def run(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug_run", ROUTEA / "plug_run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug_run"] = module
    spec.loader.exec_module(module)
    return module


def test_decide_needs_a_positive_interval_and_the_minimum_gain(run):
    assert run.decide([0.3, 0.25, 0.35, 0.3, 0.28])["decision"] == "better"
    assert run.decide([0.02, 0.03, 0.01, 0.02, 0.03])["decision"] == "tie"  # above 0, under 0.05
    assert run.decide([-0.3, -0.25, -0.35, -0.3])["decision"] == "worse"
    assert run.decide([0.3, -0.3, 0.2, -0.2])["decision"] == "tie"


def test_confabulation_control_has_an_absolute_bar(run):
    assert run.confabulation_control([0.0] * 6, [0.0] * 6)["passes"]
    high = run.confabulation_control([0.3] * 6, [0.3] * 6)
    assert not high["passes"]
    worse = run.confabulation_control([0.09, 0.08, 0.09, 0.08], [0.0] * 4)
    assert worse["a1_minus_a2"]["decision"] == "worse"
    assert not worse["passes"]


def prereg_plan(run):
    names = sorted(run.SCORED)
    return {
        "test_repos": dict(run.SCORED),
        "control_of": {repo: names[(i + 1) % len(names)] for i, repo in enumerate(names)},
        "meta_train_repos": ["r"] * run.META_REPOS,
        "meta_train_rows": run.META_ROWS,
        "meta_rows_dropped_too_long": run.META_DROPPED,
        "shared_key_lesson_ids": ["x"] * run.SHARED_KEY_LESSONS,
    }


def test_plan_must_match_the_prereg_table(run):
    plan = prereg_plan(run)
    run.check_plan(plan)
    changes = {
        "test_repos": {**run.SCORED, "org/extra": 10},
        "meta_train_rows": run.META_ROWS - 1,
        "meta_rows_dropped_too_long": 0,
        "shared_key_lesson_ids": [],
        "control_of": {**plan["control_of"], "hylang/hy": "scipp/plopp"},
    }
    for key, value in changes.items():
        with pytest.raises(run.PlanMismatchError, match=key.replace("_lesson_ids", "_lessons")):
            run.check_plan({**plan, key: value})


def decisions_with(h1, *, control_passes=True, works=False):
    return {
        "h1_a2_vs_a1_at_5": {
            "decision": h1[0],
            "mean_gain": h1[1],
            "ci95_low": h1[2],
            "ci95_high": h1[3],
        },
        "confabulation_control_at_5": {"passes": control_passes},
        "plug_and_play_works": works,
    }


ROWS_AT_5 = [
    {"row": "a2", "budget": 5, "reworded": 0.61},
    {"row": "a1", "budget": 5, "reworded": 0.32},
]


def test_verdict_sentence_follows_the_prereg_wording(run):
    habits = {"a2": {"ranked": 0.9}, "plain": {"ranked": 0.2}}
    works = run.verdict_sentence(
        decisions_with(("better", 0.29, 0.2, 0.38), works=True), ROWS_AT_5, habits
    )
    assert works.startswith("recalls 0.61 of the reworded probes with 5 lessons in the prompt")
    assert "against 0.32 for the plain model, without per-repo training" in works
    tie = run.verdict_sentence(decisions_with(("tie", 0.03, -0.05, 0.11)), ROWS_AT_5, habits)
    assert tie.startswith("a meta-trained reader did not measurably beat the plain model")
    assert "+0.03" in tie


def test_verdict_sentence_names_a_failed_control_and_lost_habits(run):
    habits = {"a2": {"ranked": 0.1}, "plain": {"ranked": 0.2}}
    found = decisions_with(("better", 0.29, 0.2, 0.38), control_passes=False)
    sentence = run.verdict_sentence(found, ROWS_AT_5, habits)
    assert "recalls more and confabulates more" in sentence
    assert "recalls more and keeps fewer habits" in sentence


def lesson(run, lesson_id, added, error="TypeError"):
    return run.Lesson(
        lesson_id=lesson_id,
        repo="org/r",
        program="pytest",
        file="tests/test_a.py",
        failed="pytest",
        error=f"{error}: boom",
        error_class=error,
        fix="pytest " + " ".join(added),
        added=added,
    )


def test_recall_cell_and_prompt_rates(run):
    own = [lesson(run, "o1", ("--own",))]
    wrong = [lesson(run, "w1", ("--wrong",), error="KeyError")]
    asked = run.probes(own)
    answers = {p["question_id"]: "TypeError; run pytest --own" for p in asked}
    cell = run.recall_cell(asked, answers, own)
    assert cell["reworded"] == 1.0 and cell["verbatim"] == 1.0
    confab = {p["question_id"]: "run pytest --wrong" for p in asked}
    assert run.prompt_rates(asked, confab, own, wrong)["confabulation"] == 1.0
    abstain = {p["question_id"]: "No lesson I hold covers that." for p in asked}
    assert run.prompt_rates(asked, abstain, own, wrong) == {"confabulation": 0.0, "abstention": 1.0}
    with pytest.raises(KeyError):
        run.recall_cell(asked, {}, own)
