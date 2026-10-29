"""Plug split checks, confabulation, abstention and ranked choice, on hand-written lessons."""

import importlib.util
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from symbiont.eval.prereg_git import PreregNotFrozenError

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
def plug(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug", ROUTEA / "plug.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug"] = module
    spec.loader.exec_module(module)
    return module


def lesson(plug, repo, lesson_id, error="TypeError", added=("--flag",), fix="pytest --flag"):
    return plug.Lesson(
        lesson_id=lesson_id,
        repo=repo,
        program="pytest",
        file="tests/test_a.py",
        failed="pytest",
        error=f"{error}: boom",
        error_class=error,
        fix=fix,
        added=added,
    )


def repo_of(plug, repo, count, prefix):
    return [lesson(plug, repo, f"{prefix}{n:03d}", added=(f"--{prefix}{n}",)) for n in range(count)]


def test_split_names_scored_and_meta_repos_and_pairs_controls_by_name(plug):
    by_repo = {
        "org/big1": repo_of(plug, "org/big1", 10, "a"),
        "org/big2": repo_of(plug, "org/big2", 12, "b"),
        "org/small": repo_of(plug, "org/small", 3, "c"),
        "org/single": repo_of(plug, "org/single", 1, "d"),
        "Azure/msrest-for-python": repo_of(plug, "Azure/msrest-for-python", 13, "e"),
    }
    split = plug.plan_split(by_repo, habit_repos=["aidev/repo"])
    assert sorted(split.test) == ["org/big1", "org/big2"]
    assert sorted(split.meta) == ["org/small"]
    assert split.control_of == {"org/big1": "org/big2", "org/big2": "org/big1"}


def test_split_refuses_a_shared_repo_or_lesson_id(plug):
    test = {"org/big": repo_of(plug, "org/big", 10, "a")}
    meta = {"org/small": [lesson(plug, "org/small", "a000", added=("--x",))]}
    with pytest.raises(plug.SharedSplitError, match="lesson ids"):
        plug.check_unseen(plug.Split(test, meta, {}), habit_repos=[])
    with pytest.raises(plug.SharedSplitError, match="habit rows and scored"):
        plug.check_unseen(plug.Split(test, {}, {}), habit_repos=["org/big"])


def test_shared_failure_keys_are_counted_not_refused(plug):
    test = {"org/big": [lesson(plug, "org/big", "t1", added=("--same",))]}
    meta = {"org/small": [lesson(plug, "org/small", "m1", added=("--same",))]}
    split = plug.Split(test, meta, {})
    plug.check_unseen(split, habit_repos=[])
    assert plug.shared_keys(split) == ["t1"]


def test_confabulation_hit_near_miss_and_shared_key(plug):
    own = [lesson(plug, "org/r", "r1", error="KeyError", added=("--own",), fix="run --own")]
    wrong = [lesson(plug, "org/w", "w1", added=("--alpha", "--beta"), fix="tox --alpha --beta")]
    assert plug.confabulates("Run it with `--alpha` and --beta.", own, wrong)
    assert plug.confabulates("Use tox --alpha --beta", own, wrong)
    assert not plug.confabulates("Run it with --alpha only.", own, wrong)
    shared = [lesson(plug, "org/w", "w2", error="KeyError", added=("--own",), fix="run --own")]
    assert not plug.confabulates("run --own", own, shared)


def test_confabulation_refuses_a_lesson_without_fix_tokens(plug):
    with pytest.raises(ValueError):
        plug.confabulates("anything", [], [lesson(plug, "org/w", "w1", added=())])


@pytest.mark.parametrize(
    ("answer", "abstains"),
    [
        ("No lesson I hold covers that.", True),
        ("I have no lesson about that command.", True),
        ("NO LESSON matches.", True),
        ("Run pytest --flag.", False),
    ],
)
def test_abstention_forms(plug, answer, abstains):
    assert plug.abstains(answer) is abstains


def test_ranked_hit_needs_a_strict_first_place(plug):
    assert plug.ranked_hit("tests", {"tests": -1.0, "naming": -2.0})
    assert not plug.ranked_hit("tests", {"tests": -2.0, "naming": -1.0})
    assert not plug.ranked_hit("tests", {"tests": -1.0, "naming": -1.0})


def test_split_refuses_a_repo_in_both_meta_train_and_scored(plug):
    test = {"org/big": repo_of(plug, "org/big", 10, "a")}
    meta = {"org/big": [lesson(plug, "org/big", "z000", added=("--z",))]}
    with pytest.raises(plug.SharedSplitError, match="meta-train and scored share repos"):
        plug.check_unseen(plug.Split(test, meta, {}), habit_repos=[])


def test_split_refuses_a_habit_repo_in_meta_train(plug):
    meta = {"aidev/repo": [lesson(plug, "aidev/repo", "m000")]}
    with pytest.raises(plug.SharedSplitError, match="habit rows and meta-train"):
        plug.check_unseen(plug.Split({}, meta, {}), habit_repos=["aidev/repo"])


def test_the_26_aidev_habit_repos_are_kept_out_of_both_sides(plug):
    habit_repos = [f"aidev/habit{n:02d}" for n in range(26)]
    by_repo = {
        "org/big": repo_of(plug, "org/big", 10, "a"),
        "org/small": repo_of(plug, "org/small", 3, "c"),
    }
    split = plug.plan_split(by_repo, habit_repos)
    assert not set(habit_repos) & (set(split.test) | set(split.meta))
    for habit_repo in (habit_repos[0], habit_repos[25]):
        leaky = {**by_repo, habit_repo: repo_of(plug, habit_repo, 3, "h")}
        with pytest.raises(plug.SharedSplitError, match="habit rows"):
            plug.plan_split(leaky, habit_repos)


def test_a_scored_run_refuses_inputs_whose_hash_differs_from_the_prereg(plug):
    plug.verify_inputs(dict(plug.PINNED))
    for name in plug.PINNED:
        changed = {**plug.PINNED, name: "0" * 64}
        with pytest.raises(plug.InputHashMismatchError, match=name):
            plug.verify_inputs(changed)
    missing = {k: v for k, v in plug.PINNED.items() if k != "habit_rows_sha256"}
    with pytest.raises(plug.InputHashMismatchError, match="habit_rows_sha256"):
        plug.verify_inputs(missing)


def test_input_hashes_name_every_pinned_input(plug, tmp_path):
    pool = tmp_path / "pool"
    pool.mkdir()
    (pool / "a.jsonl").write_text("{}\n")
    files = {name: tmp_path / name for name in ("rows", "questions", "system")}
    for path in files.values():
        path.write_text("x")
    found = plug.input_hashes(pool, files["rows"], files["questions"], files["system"])
    assert set(found) == set(plug.PINNED)
    with pytest.raises(plug.InputHashMismatchError):
        plug.verify_inputs(found)


def test_a_scored_run_needs_the_prereg_frozen_under_its_final_name(plug, monkeypatch, tmp_path):
    draft = tmp_path / "2026-10-28-l2l-a2-DRAFT.md"
    draft.write_text("# draft\n")
    with pytest.raises(PreregNotFrozenError):
        plug.scored_run_label(str(draft))
    seen = {}
    monkeypatch.setattr(plug, "run_provenance", lambda **kwargs: seen.update(kwargs) or {})
    plug.scored_run_label("prereg/2026-10-29-l2l-a2.md")
    assert seen == {
        "scored": True,
        "prereg": "prereg/2026-10-29-l2l-a2.md",
        "expects": "2026-10-29-l2l-a2.md",
    }


@pytest.fixture
def plug_a3(monkeypatch, plug):
    spec = importlib.util.spec_from_file_location("plug_a3", ROUTEA / "plug_a3.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug_a3"] = module
    spec.loader.exec_module(module)
    return module


def test_rerun_tests_8_or_9_lesson_repos_and_keeps_scored_repos_out(plug, plug_a3):
    by_repo = {
        "org/eight": repo_of(plug, "org/eight", 8, "a"),
        "org/nine": repo_of(plug, "org/nine", 9, "b"),
        "org/ten": repo_of(plug, "org/ten", 10, "c"),
        "org/small": repo_of(plug, "org/small", 3, "d"),
    }
    split = plug_a3.plan_rerun(by_repo, scored={"org/ten"}, habit_repos=[])
    assert sorted(split.test) == ["org/eight", "org/nine"]
    assert sorted(split.meta) == ["org/small"]


def test_replay_arm_adds_one_habit_row_per_repo_row(plug_a3):
    own = [{"messages": [{"content": f"own{n}"}]} for n in range(3)]
    reading = [{"messages": [{"content": f"read{n}"}]} for n in range(10)]
    habits = [{"messages": [{"content": f"habit{n}"}]} for n in range(10)]
    plain = plug_a3.arm_rows(own, reading, habits, "a3")
    replay = plug_a3.arm_rows(own, reading, habits, "a3_replay")
    assert len(plain) == 3 + plug_a3.MIX * 3
    assert len(replay) == len(plain) + 3


def test_rerun_verdicts_follow_the_go_and_kill_rule(plug_a3):
    def row(arm, no_lessons, new):
        return {"arm": arm, "no_lessons": no_lessons, "new_lessons": new}

    rows = [
        row("per_repo", 0.5, 0.4),
        row("a1", 0.0, 0.4),
        row("a2v", 0.0, 0.6),
        row("a3", 0.6, 0.7),
        row("a3_more", 0.6, 0.5),
        row("a3_replay", 0.6, 0.3),
    ]
    assert plug_a3.verdicts(rows) == {"a3": "go", "a3_more": "hold", "a3_replay": "kill"}


def test_more_replay_must_also_keep_habits_near_a2(plug_a3):
    def row(arm, no_lessons, new, habits):
        return {"arm": arm, "no_lessons": no_lessons, "new_lessons": new, "habits_ranked": habits}

    base = [row("per_repo", 0.5, 0.4, 0.2), row("a1", 0.0, 0.4, 0.2), row("a2v", 0.0, 0.6, 0.9)]
    kept = plug_a3.verdicts([*base, row("a3_more_replay", 0.6, 0.7, 0.85)])
    lost = plug_a3.verdicts([*base, row("a3_more_replay", 0.6, 0.7, 0.70)])
    assert kept == {"a3_more_replay": "go"}
    assert lost == {"a3_more_replay": "hold"}


@pytest.fixture
def distract(monkeypatch, plug):
    spec = importlib.util.spec_from_file_location("plug_distract", ROUTEA / "plug_distract.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug_distract"] = module
    spec.loader.exec_module(module)
    return module


def test_distract_rows_mix_own_and_other_lessons_and_abstain_without_own(plug, distract):
    by_repo = {
        "org/a": repo_of(plug, "org/a", 2, "a"),
        "org/b": repo_of(plug, "org/b", 3, "b"),
    }
    rows = distract.distract_rows(by_repo)
    abstain = [r for r in rows if r["messages"][2]["content"] == distract.ABSTAIN]
    answered = [r for r in rows if r["messages"][2]["content"] != distract.ABSTAIN]
    assert len(abstain) == 5  # one per lesson
    for row in answered:
        prompt = row["messages"][0]["content"]
        assert "In org/a" in prompt and "In org/b" in prompt  # own and another repo's lessons


def test_mixed_context_is_one_fixed_order(plug, distract):
    own = repo_of(plug, "org/a", 2, "a")
    wrong = repo_of(plug, "org/b", 2, "b")
    first = distract.mixed_context(own, wrong)
    assert first == distract.mixed_context(own, wrong)
    assert first.count("In org/a") == 2 and first.count("In org/b") == 2


class FakeGit:
    """Answers the three git calls the code guard makes."""

    def __init__(self, *, differs=False, dirty=""):
        self.differs, self.dirty, self.calls = differs, dirty, []

    def __call__(self, root, *args):
        self.calls.append(args)
        if args[0] == "rev-parse":
            return CompletedProcess(args, 0, stdout="abc123\n", stderr="")
        if args[0] == "diff":
            return CompletedProcess(args, 1 if self.differs else 0, stdout="", stderr="")
        return CompletedProcess(args, 0, stdout=self.dirty, stderr="")


def test_code_guard_returns_head_when_code_matches_the_freeze_commit(plug, tmp_path):
    git = FakeGit()
    assert plug.pinned_code_commit(tmp_path, "f00d", git) == "abc123"
    diff = next(call for call in git.calls if call[0] == "diff")
    assert diff[:4] == ("diff", "--quiet", "f00d", "HEAD")
    assert set(diff[5:]) == set(plug.GUARDED_CODE)


def test_code_guard_refuses_changed_or_uncommitted_code(plug, tmp_path):
    with pytest.raises(plug.CodeNotPinnedError, match="differs"):
        plug.pinned_code_commit(tmp_path, "f00d", FakeGit(differs=True))
    with pytest.raises(plug.CodeNotPinnedError, match="uncommitted"):
        plug.pinned_code_commit(tmp_path, "f00d", FakeGit(dirty=" M scripts/routea/plug.py\n"))


def test_scored_provenance_records_the_code_commit(plug, monkeypatch, tmp_path):
    label = {"freeze_commit": "f00d", "prereg_sha256": "beef", "run_label": "scored"}
    monkeypatch.setattr(plug, "scored_run_label", lambda prereg: dict(label))
    found = plug.scored_provenance("prereg/x.md", tmp_path, FakeGit())
    assert found == {**label, "code_commit": "abc123"}
