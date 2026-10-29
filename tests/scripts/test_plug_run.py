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


def test_plan_must_match_the_prereg_table(run):
    plan = {
        "test_repos": dict(run.SCORED),
        "meta_train_repos": ["r"] * run.META_REPOS,
        "meta_train_rows": run.META_ROWS,
    }
    run.check_plan(plan)
    with pytest.raises(run.PlanMismatchError):
        run.check_plan({**plan, "test_repos": {**run.SCORED, "org/extra": 10}})
    with pytest.raises(run.PlanMismatchError):
        run.check_plan({**plan, "meta_train_rows": run.META_ROWS - 1})


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
