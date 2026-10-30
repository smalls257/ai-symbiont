"""Plug round 4's primary items, pins and statistics on hand-written repositories."""

import importlib.util
import json
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


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location(name, ROUTEA / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def primary(monkeypatch):
    return load(monkeypatch, "plug_r4_primary")


def lesson(primary, repo, number, fix="--opt"):
    return primary.Lesson(
        lesson_id=f"{repo}-{number}-{fix}",
        repo=repo,
        program="pytest",
        file=f"tests/t{number}.py",
        failed=f"pytest tests/t{number}.py",
        error=f"TypeError: boom {number}",
        error_class="TypeError",
        fix=f"pytest tests/t{number}.py {fix}",
        added=(fix,),
    )


def failure(primary, task, number):
    return primary.Failure(
        task, f"pytest tests/t{number}.py", f"TypeError: boom {number}", f"tests/t{number}.py"
    )


def events(primary, repo):
    """Task a mined lesson 1; task b fails on 1 again (recurrence) and on 9 (no lesson)."""
    first = primary.TaskEvents("a", "2024-01-01", (), (lesson(primary, repo, 1),))
    later = primary.TaskEvents(
        "b", "2024-02-01", (failure(primary, "b", 1), failure(primary, "b", 9)), ()
    )
    return [later, first]  # given out of order on purpose


def test_a_recurrence_is_positive_and_the_unmatched_failure_is_a_negative(primary):
    cases = primary.repo_cases("o/r", events(primary, "o/r"))
    assert [bool(c.matches) for c in cases] == [True, False]


def test_the_first_task_has_no_store_and_gives_no_case(primary):
    only = [primary.TaskEvents("a", "2024-01-01", (failure(primary, "a", 1),), ())]
    assert primary.repo_cases("o/r", only) == []


def test_a_loose_only_match_is_neither_positive_nor_negative(primary):
    store = primary.TaskEvents("a", "2024-01-01", (), (lesson(primary, "o/r", 1),))
    loose = primary.Failure("b", "cd /x && pytest tests/t1.py", "TypeError: boom 1", "tests/t1.py")
    # same command after normalization but a different error text is a different key either way
    other = primary.Failure("b", "pytest tests/t1.py", "TypeError: other", "tests/t1.py")
    later = primary.TaskEvents("b", "2024-02-01", (other,), ())
    assert [c.matches for c in primary.repo_cases("o/r", [store, later])] == [()]
    assert loose.exact() != other.exact()


def test_identical_lessons_merge_but_different_fixes_stay_twins(primary):
    same = [lesson(primary, "o/r", 1), lesson(primary, "o/r", 1)]
    twins = [lesson(primary, "o/r", 1, "--a"), lesson(primary, "o/r", 1, "--b")]
    assert len(primary.merged_store(same)) == 1
    assert len(primary.merged_store(twins)) == 2


def test_negatives_match_the_repository_s_positive_count(primary):
    extra = primary.TaskEvents(
        "c", "2024-03-01", tuple(failure(primary, "c", n) for n in (7, 8, 9)), ()
    )
    cases = primary.repo_cases("o/r", [*events(primary, "o/r"), extra])
    chosen = primary.chosen_negatives(cases)
    assert len(chosen) == sum(1 for c in cases if c.matches) == 1
    assert primary.chosen_negatives(cases) == chosen  # seeded, so repeatable


def test_the_build_refuses_a_count_other_than_the_declared_one(primary):
    item = primary.Item("i-pick", "s", (), lesson(primary, "o/r", 1))
    with pytest.raises(primary.PrimaryCountError):
        primary.checked_counts([item], {"i-pick": "o/r"})


def test_primary_repos_are_never_read_and_meta2_only_with_a_recurrence_plus_the_rest(primary):
    fresh = {"repos": [{"repo": "a/x"}, {"repo": "b/y"}, {"repo": "c/z"}]}
    recur = {"nebius": {"exact": {"per_repo": {"a/x": 2, "plug/old": 3, "c/z": 1}}}}
    rest = {"nebius": {"exact": {"per_repo": {"d/w": 1}}}}
    assert primary.primary_repos(fresh, recur, rest) == {"a/x", "c/z", "d/w"}


@pytest.fixture
def scored(monkeypatch):
    load(monkeypatch, "plug_r4_primary")
    return load(monkeypatch, "plug_r4_scored")


def write_primary(directory: Path, positives=251, repos=89):
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("primary-items.jsonl", "primary-queries.jsonl", "primary-negatives.txt"):
        (directory / name).write_text(name)
    manifest = {"positives": positives, "positive_repos": repos, "negatives": 10}
    (directory / "primary-manifest.json").write_text(json.dumps(manifest))


def write_adapters(directory: Path):
    for seed in range(3):
        folder = directory / f"judge-s{seed}"
        folder.mkdir(parents=True)
        (folder / "adapter_model.safetensors").write_text(str(seed))


def pins_for(scored, tmp_path):
    write_primary(tmp_path / "p")
    write_adapters(tmp_path / "a")
    (tmp_path / "sel.json").write_text("{}")
    now = scored.current_pins(tmp_path / "p", tmp_path / "a", tmp_path / "sel.json")
    (tmp_path / "pins.json").write_text(json.dumps(now))
    return tmp_path


def run_check(scored, tmp_path):
    return scored.check(
        tmp_path / "p", tmp_path / "a", tmp_path / "sel.json", tmp_path / "pins.json"
    )


def test_check_passes_on_unchanged_files(scored, tmp_path):
    assert run_check(scored, pins_for(scored, tmp_path))["positives"] == 251


@pytest.mark.parametrize(
    "victim",
    [
        "p/primary-negatives.txt",
        "p/primary-items.jsonl",
        "sel.json",
        "a/judge-s1/adapter_model.safetensors",
    ],
)
def test_check_refuses_any_changed_pinned_file(scored, tmp_path, victim):
    pins_for(scored, tmp_path)
    (tmp_path / victim).write_text("changed")
    with pytest.raises(scored.PinMismatchError):
        run_check(scored, tmp_path)


def test_check_refuses_a_smaller_item_set_even_if_pinned(scored, tmp_path):
    pins_for(scored, tmp_path)
    write_primary(tmp_path / "p", positives=250, repos=89)
    (tmp_path / "pins.json").write_text(
        json.dumps(scored.current_pins(tmp_path / "p", tmp_path / "a", tmp_path / "sel.json"))
    )
    with pytest.raises(scored.PinMismatchError, match="n = 250"):
        run_check(scored, tmp_path)


def write_scores(directory: Path, queries: list[str], value=0.5, drop=None):
    directory.mkdir(parents=True, exist_ok=True)
    for seed in range(3):
        rows = [{"question_id": q, "p_yes": value} for q in queries if q != drop]
        (directory / f"primary-judge-s{seed}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows)
        )
    (directory / "q.jsonl").write_text(
        "".join(json.dumps({"question_id": q}) + "\n" for q in queries)
    )


def test_scores_are_read_when_complete(scored, tmp_path):
    write_scores(tmp_path, ["a::1", "a::2"])
    assert scored.read_scores(tmp_path, tmp_path / "q.jsonl") == {"a::1": 0.5, "a::2": 0.5}


def test_a_missing_query_score_is_refused_not_read_as_silence(scored, tmp_path):
    write_scores(tmp_path, ["a::1", "a::2"], drop="a::2")
    with pytest.raises(scored.PinMismatchError):
        scored.read_scores(tmp_path, tmp_path / "q.jsonl")


def test_a_missing_seed_file_is_refused(scored, tmp_path):
    write_scores(tmp_path, ["a::1"])
    (tmp_path / "primary-judge-s2.jsonl").unlink()
    with pytest.raises(scored.PinMismatchError, match="missing"):
        scored.read_scores(tmp_path, tmp_path / "q.jsonl")


def test_a_score_outside_zero_one_is_refused(scored, tmp_path):
    write_scores(tmp_path, ["a::1"], value=1.5)
    with pytest.raises(scored.PinMismatchError):
        scored.read_scores(tmp_path, tmp_path / "q.jsonl")


@pytest.fixture
def stats(monkeypatch):
    return load(monkeypatch, "plug_r4_primary_stats")


def table(stats, positives, right, items, wrong, answered=None):
    import numpy as np

    return stats.RepoTable(
        tuple(f"r{i}" for i in range(len(positives))),
        *(np.array(x, dtype=float) for x in (positives, right, items, wrong, answered or right)),
    )


def test_coverage_is_the_per_repo_mean_not_the_pooled_rate(stats):
    one = table(stats, [1, 9], [1, 0], [1, 9], [0, 0])
    assert stats.coverage(one) == pytest.approx(0.5)  # pooled would be 0.1


def test_wrong_pick_counts_negatives_in_its_denominator(stats):
    one = table(stats, [1], [1], [3], [1])
    assert stats.pooled_wrong(one) == pytest.approx(1 / 3)


def test_the_bootstrap_resamples_repositories_and_is_repeatable(stats):
    rule = table(stats, [2] * 6, [2, 2, 1, 2, 2, 1], [4] * 6, [0] * 6)
    alone = table(stats, [2] * 6, [1, 0, 1, 1, 0, 1], [4] * 6, [0] * 6)
    first, second = stats.bootstrap(rule, alone), stats.bootstrap(rule, alone)
    assert first == second and first["gain_low"] < first["gain_mean"] < first["gain_high"]


@pytest.mark.parametrize(
    "gain, low, high, want",
    [
        (0.2, 0.1, 0.3, "better"),
        (0.2, -0.1, 0.4, "tie"),
        (-0.2, -0.3, -0.1, "worse"),
        (0.03, 0.01, 0.05, "tie"),
    ],
)
def test_verdicts(stats, gain, low, high, want):
    assert stats.verdict(gain, low, high) == want


def test_safety_needs_both_the_rate_and_the_bound(stats):
    assert stats.safety(0.04, 0.09) == "safe"
    assert stats.safety(0.04, 0.12) == "safety not shown"
    assert stats.safety(0.06, 0.08) == "safety not shown"


def test_the_claim_always_carries_the_judge_alone(scored):
    found = {
        "coverage_rule": 0.5,
        "coverage_judge_alone": 0.3,
        "gain": 0.2,
        "gain_interval": [0.1, 0.3],
        "reading": "better",
        "items": 501,
        "repos_without_positives_excluded": 0,
        "wrong_bound_rule": 0.07,
        "rule": {"wrong_pick": 0.04},
        "judge_alone": {"wrong_pick": 0.05},
        "safety": "safe",
    }
    sentence = scored.claim(found)
    assert "0.3 for the judge alone" in sentence and "251 real later recurrences" in sentence
    assert "over all 501 primary items, negatives included" in sentence


def test_icc_with_no_wrong_picks_is_zero_not_a_crash(monkeypatch):
    power = load(monkeypatch, "plug_r4_power")
    assert power.icc({"a": [0, 0], "b": [0, 0, 0]}) == 0.0
