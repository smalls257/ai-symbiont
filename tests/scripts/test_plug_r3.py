"""Plug round 3's split checks, thresholded ranker, mix, gates and claim on hand-written items."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
SCRIPT_DIRS = {ROUTEA, ROUTEA.parent / "aidev"}
CLAIM_CAP = 260  # check_results_content's MAX_LABEL_CHARS for the `result` field


@pytest.fixture(autouse=True)
def forget_script_modules():
    """Drop only modules loaded from scripts/; shared libraries stay loaded."""
    yield
    for name, module in list(sys.modules.items()):
        if Path(getattr(module, "__file__", None) or "/").parent in SCRIPT_DIRS:
            del sys.modules[name]


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location(name, ROUTEA / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def r3(monkeypatch):
    return load(monkeypatch, "plug_r3")


@pytest.fixture
def decide(monkeypatch):
    return load(monkeypatch, "plug_r3_decide")


def lesson(r3, repo, number, error_class="TypeError"):
    return r3.Lesson(
        lesson_id=f"{repo}-{number}",
        repo=repo,
        program="pytest",
        file=f"tests/test_{number}.py",
        failed=f"pytest tests/test_{number}.py",
        error=f"{error_class}: boom {number}",
        error_class=error_class,
        fix=f"pytest tests/test_{number}.py --opt{number}",
        added=(f"--opt{number}",),
    )


def splits(r3):
    return {
        "meta": {"org/m": [lesson(r3, "org/m", 1)]},
        "validation": {"org/v": [lesson(r3, "org/v", 2)]},
        "scored": {"org/s": [lesson(r3, "org/s", 3)]},
    }


def test_split_check_counts_keys_shared_with_meta(r3):
    found = splits(r3)
    found["scored"]["org/s"].append(lesson(r3, "org/s", 1))  # same key as the meta lesson
    assert r3.check_splits(found, ["org/h"]) == {"scored": 1, "validation": 0}


@pytest.mark.parametrize(
    "left, right", [("validation", "meta"), ("validation", "scored"), ("meta", "scored")]
)
def test_split_check_refuses_a_shared_repo(r3, left, right):
    found = splits(r3)
    found[left]["org/shared"] = [lesson(r3, "org/shared", 7)]
    found[right]["org/shared"] = [lesson(r3, "org/shared", 8)]
    with pytest.raises(r3.SharedSplitError):
        r3.check_splits(found, [])


def test_split_check_refuses_a_shared_lesson_id(r3):
    found = splits(r3)
    found["validation"]["org/v"].append(found["meta"]["org/m"][0])
    with pytest.raises(r3.SharedSplitError):
        r3.check_splits(found, [])


def test_split_check_refuses_a_habit_repo_in_validation(r3):
    with pytest.raises(r3.SharedSplitError):
        r3.check_splits(splits(r3), ["org/v"])


def test_meta_list_other_than_the_prereg_is_refused(r3):
    with pytest.raises(r3.MetaListMismatchError):
        r3.check_meta(splits(r3))


def item_pair(r3, right, others):
    situation = (
        f"Ran `{right.failed}` in {right.repo} (file {right.file}). It failed: {right.error}"
    )
    pick = r3.Item(f"{right.lesson_id}-pick", situation, (*others, right), right)
    quiet = r3.Item(f"{right.lesson_id}-silence", situation, tuple(others), None)
    return pick, quiet


def pairs(r3):
    others = [lesson(r3, "org/x", n, "ValueError") for n in range(10, 16)]
    rights = [lesson(r3, "org/r", n) for n in (1, 2)]
    return rights, others, [i for right in rights for i in item_pair(r3, right, others)]


def test_thresholded_ranker_answers_only_above_its_threshold(r3):
    _, _, found = pairs(r3)
    loud = r3.ranker_choices(found, float("-inf"))
    assert all(choice.lesson_id is not None for choice in loud)
    assert all(choice.lesson_id is None for choice in r3.ranker_choices(found, 1e9))


def test_fit_returns_none_when_no_point_is_safe(r3):
    _, _, found = pairs(r3)
    always = lambda threshold: r3.ranker_choices(found, float("-inf"))  # noqa: E731
    assert r3.fit_lowest(found, always, [0.0, 1.0]) is None


def test_per_repo_refuses_a_repo_without_silence_items(r3):
    _, _, found = pairs(r3)
    picks = [item for item in found if item.applies is not None]
    choices = r3.ranker_choices(picks, 0.0)
    with pytest.raises(ValueError, match="pick and silence"):
        r3.per_repo(picks, choices, {item.item_id: "org/r" for item in picks})


def test_seen_set_uses_the_frozen_wording(r3):
    rights, _, found = pairs(r3)
    seen = r3.reworded(found, rights, r3.SEEN_WORDING)
    assert seen[0].situation.startswith("Something broke. Repo: org/r.")
    assert seen[1].situation == seen[0].situation  # the silence item shares its lesson's wording


def test_wrong_picks_of_meta_lessons_are_counted(r3):
    _, others, found = pairs(r3)
    choices = [r3.Choice(item.item_id, others[0].lesson_id, 1.0) for item in found]
    assert r3.wrong_from(found, choices, {others[0].lesson_id}) == {"wrong_picks": 4, "share": 1.0}


def test_mix_balances_every_phrasing_and_adds_habits(r3, monkeypatch):
    judge = load(monkeypatch, "plug_judge")
    rights, _, found = pairs(r3)
    habits = [{"messages": []}] * 3
    mix = judge.judge_mix(found, 10, [lambda x: f"again {x.failed}"], r3.source_of(rights), habits)
    assert mix["counts"]["phrasings"] == 2
    assert mix["counts"]["positives"] == mix["counts"]["negatives"] == 4
    assert mix["counts"]["total"] == 11 and len(mix["rows"]) == 11


def cells(pick, silence=0.9, wrong=0.02, repos=10):
    cell = {"pick": pick, "silence": silence, "wrong_pick": wrong, "precision": 0.9, "answered": 3}
    return {f"r{n}": dict(cell) for n in range(repos)}


def test_safety_gate_reads_the_wrong_pick_upper_bound(decide):
    assert decide.safety_gate(cells(0.5))["passes"]
    noisy = cells(0.5) | {"r0": {"pick": 0.5, "silence": 0.9, "wrong_pick": 0.5}}
    assert not decide.safety_gate(noisy)["passes"]


def test_habits_gate_prints_its_interval_and_the_untrained(decide):
    found = decide.habits_gate(0.93, 0.5, 44)
    assert found["passes"] and found["untrained_1b"] == 0.5
    assert found["judge_wilson95"][0] < 0.93 < found["judge_wilson95"][1]


def test_new_lesson_gate_fails_a_wide_gap(decide):
    assert decide.new_lesson_gate(cells(0.7), cells(0.72))["passes"]
    assert not decide.new_lesson_gate(cells(0.5), cells(0.9))["passes"]


def test_power_flags_an_underpowered_round(decide):
    assert decide.power([0.0, 0.6, 0.1, 0.5, 0.2], 8.3, 4.1)["underpowered"]


def means():
    row = {"pick": 0.6, "precision": 0.9, "wrong_pick": 0.03, "silence": 0.9}
    alone = {"pick": 0.8, "precision": 0.4, "wrong_pick": 0.6, "silence": 0.0}
    return {"judge": row, "ranker_alone": alone, "ranker_threshold": {"pick": 0.15}}


def gates(failing=()):
    return {name: {"passes": name not in failing} for name in ("safety", "habits", "new lessons")}


@pytest.mark.parametrize(
    "judge_pick, ranker, failing, words",
    [
        (0.6, 0.1, (), "on situations built from each lesson's own record"),
        (0.6, 0.1, ("safety",), "failed the safety gate"),
        (0.3, 0.3, (), "(tie,"),
        (0.0, 0.6, (), "(worse,"),
        (0.6, None, (), "the ranker could not be made silent at these limits"),
    ],
)
def test_claim_branches_carry_the_ranker_alone(decide, judge_pick, ranker, failing, words):
    first = decide.h1(cells(judge_pick), None if ranker is None else cells(ranker))
    sentence = decide.claim(first, gates(failing), means())
    assert words in sentence
    assert "(ranker alone 0.80, 0.40, 0.60)" in sentence
    assert len(sentence) <= CLAIM_CAP


def test_no_safe_comparator_is_never_better(decide):
    assert decide.h1(cells(0.9), None) == {"decision": "no safe comparator"}


def test_check_passes_its_prereg_name_through(monkeypatch, tmp_path):
    score = load(monkeypatch, "plug_r2_score")
    seen = {}
    monkeypatch.setattr(score, "pool_index_sha", lambda path: "p")
    monkeypatch.setattr(score, "sha256_of", lambda path: "h")
    monkeypatch.setattr(score, "verify_pins", lambda found: None)
    monkeypatch.setattr(score, "check_plan", lambda plan: None)
    monkeypatch.setattr(score, "pinned_code_commit", lambda root, commit: commit)
    monkeypatch.setattr(
        score, "run_provenance", lambda **kw: seen.update(kw) or {"freeze_commit": "c"}
    )
    (tmp_path / "plan.json").write_text("{}")
    args = type("Args", (), {"pool": 0, "habit_rows": 0, "aidev_lessons": 0, "prereg": 0})()
    args.work = tmp_path
    score.check(args, expects="2026-10-29-plug-judge.md")
    assert seen["expects"] == "2026-10-29-plug-judge.md"


def test_precision_pairs_only_repos_where_the_judge_spoke(decide):
    judge, alone = cells(0.5), cells(0.8)
    judge["r0"] |= {"answered": 0, "precision": 1.0}
    assert decide.versus_alone(judge, alone)["precision"]["repos"] == 9


def test_claim_prints_na_when_the_judge_never_answered(decide):
    silent = means() | {"judge": means()["judge"] | {"precision": None}}
    first = decide.h1(cells(0.0), cells(0.2))
    assert "0.60, n/a, 0.03" in decide.claim(first, gates(), silent)
