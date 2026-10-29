"""Plug round 2's rows, fit, selection and scored decisions on hand-written data."""

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


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location(name, ROUTEA / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def lesson(module, repo, number, error="TypeError"):
    return module.Lesson(
        lesson_id=f"{repo}-{number}",
        repo=repo,
        program="pytest",
        file=f"tests/test_{number}.py",
        failed=f"pytest tests/test_{number}.py",
        error=f"{error}: boom {number}",
        error_class=error,
        fix=f"pytest tests/test_{number}.py --opt{number}",
        added=(f"--opt{number}",),
    )


def meta_of(module, repos=20, per_repo=4):
    return {
        f"org/m{r}": [lesson(module, f"org/m{r}", r * 10 + n) for n in range(per_repo)]
        for r in range(repos)
    }


def test_meta_split_holds_out_scored_and_validation_and_refuses_overlap(monkeypatch):
    rows = load(monkeypatch, "plug_r2_rows")
    by_repo = meta_of(rows, repos=4)
    plan = {"scored": {"org/m0": 4}, "validation": ["org/m1"]}
    split = rows.meta_split(by_repo, plan, habit_repos=[])
    assert sorted(split.meta) == ["org/m2", "org/m3"]
    with pytest.raises(rows.SharedSplitError if hasattr(rows, "SharedSplitError") else ValueError):
        rows.meta_split(by_repo, plan, habit_repos=["org/m2"])


def test_situation_rows_pick_and_silence_on_five_shuffled_lessons(monkeypatch):
    rows = load(monkeypatch, "plug_r2_rows")
    meta = meta_of(rows)
    built = rows.situation_rows(meta)
    assert len(built) == 2 * sum(len(v) for v in meta.values())
    abstain = [r for r in built if r["messages"][2]["content"] == rows.ABSTAIN]
    assert len(abstain) == len(built) // 2
    for row in built:
        assert row["messages"][0]["content"].count("\n- ") == rows.TOP
        assert row["messages"][1]["content"].startswith("The agent is now doing this")


def test_v2_adds_fourteen_phrasings_and_v3_adds_unrelated_lessons(monkeypatch):
    rows = load(monkeypatch, "plug_r2_rows")
    meta = meta_of(rows)
    base = rows.situation_rows(meta)
    v2 = rows.situation_rows(meta, rows.PHRASINGS)
    assert len(rows.PHRASINGS) == 14 and len(v2) == 15 * len(base)
    v3 = rows.with_unrelated(base, ["habit one", "habit two", "habit three"])
    assert all(r["messages"][0]["content"].count("\n- ") == rows.TOP + rows.UNRELATED for r in v3)


def test_variant_rows_reject_v4_and_unknown(monkeypatch):
    rows = load(monkeypatch, "plug_r2_rows")
    split = rows.Split({}, meta_of(rows), {})
    for name in ("V4", "V9"):
        with pytest.raises(ValueError):
            rows.variant_rows(name, split, [], [])


class FakeTokenizer:
    """One token per word; the chat template joins the contents."""

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": text.split()}

    def apply_chat_template(self, messages, tokenize=False):
        return " ".join(m["content"] for m in messages)


def test_fit_drops_and_counts_long_rows_and_long_answers(monkeypatch):
    fit = load(monkeypatch, "fit_rows")
    short = {"messages": [{"content": "sys"}, {"content": "q"}, {"content": "a b"}]}
    long_answer = {"messages": [{"content": "sys"}, {"content": "q"}, {"content": "w " * 10}]}
    long_row = {"messages": [{"content": "w " * 20}, {"content": "q"}, {"content": "a"}]}
    kept, dropped = fit.fit(
        FakeTokenizer(), [short, long_answer, long_row], max_tokens=10, max_answer=5
    )
    assert kept == [short]
    assert dropped == {"row_over_window": 1, "answer_over_budget": 1}


def cell(pick, silence=0.9, wrong=0.0):
    return {"pick": pick, "useful": pick, "silence": silence, "wrong_pick": wrong}


def test_gate_needs_silence_and_low_wrong_pick(monkeypatch):
    select = load(monkeypatch, "plug_r2_select")
    good = {f"r{n}": cell(0.5, silence=0.95, wrong=0.0) for n in range(6)}
    assert select.gate(good)["passes"]
    quiet = {f"r{n}": cell(0.5, silence=0.5) for n in range(6)}
    assert not select.gate(quiet)["passes"]
    noisy = {f"r{n}": cell(0.5, silence=0.95, wrong=0.2) for n in range(6)}
    assert not select.gate(noisy)["passes"]


def test_selection_v1_against_floor_needs_the_gate_and_stops_if_v1_fails(monkeypatch):
    select = load(monkeypatch, "plug_r2_select")
    floor = {f"r{n}": cell(0.0, silence=1.0) for n in range(6)}
    v1 = {f"r{n}": cell(0.6 + n * 0.01, silence=0.95) for n in range(6)}
    v1_loud = {f"r{n}": cell(0.6 + n * 0.01, silence=0.2) for n in range(6)}
    assert select.select({"floor": floor, "V1": v1}, ["V1"])["selected"] == "V1"
    stopped = select.select({"floor": floor, "V1": v1_loud, "V2": v1}, ["V1", "V2"])
    assert stopped["selected"] == "floor" and len(stopped["steps"]) == 1


def test_later_variants_need_pick_gain_without_losing_silence_or_adding_wrong(monkeypatch):
    select = load(monkeypatch, "plug_r2_select")
    floor = {f"r{n}": cell(0.0, silence=1.0) for n in range(6)}
    v1 = {f"r{n}": cell(0.5 + n * 0.01, silence=0.95) for n in range(6)}
    v2_better = {f"r{n}": cell(0.7 + n * 0.01, silence=0.95) for n in range(6)}
    v2_quieter = {f"r{n}": cell(0.7 + n * 0.01, silence=0.85) for n in range(6)}
    v2_tie = {f"r{n}": cell(0.51 + n * 0.01, silence=0.95) for n in range(6)}
    for v2, expected in ((v2_better, "V2"), (v2_quieter, "V1"), (v2_tie, "V1")):
        found = select.select({"floor": floor, "V1": v1, "V2": v2}, ["V1", "V2"])
        assert found["selected"] == expected


def test_mde_matches_the_prereg_formula(monkeypatch):
    select = load(monkeypatch, "plug_r2_select")
    gains = [0.1, 0.3, 0.2, 0.4, 0.0]
    found = select.mde(gains, validation_items=8.0, scored_items=4.0)
    sd = 0.1581  # sample standard deviation of the gains
    scaled = sd * (8.0 / 4.0) ** 0.5
    assert found["sd_validation"] == pytest.approx(sd, abs=1e-4)
    expected = max(0.05, 1.96 * scaled / 40**0.5) + 0.84 * scaled / 40**0.5
    assert found["mde"] == pytest.approx(expected, abs=1e-3)


def test_plan_check_and_bare_records(monkeypatch):
    score = load(monkeypatch, "plug_r2_score")
    score.check_plan({"scored": dict(score.SCORED), "meta_join": dict(score.META_JOIN)})
    with pytest.raises(score.PlanMismatchError):
        score.check_plan({"scored": {}, "meta_join": dict(score.META_JOIN)})
    sit = load(monkeypatch, "plug_situation")
    right = lesson(sit, "org/r", 1)
    record = sit.item_record(sit.Item("x-pick", "s", (right,), right)) | {"repo": "org/r"}
    (bare,) = score.bare_records([record])
    assert bare["prompt_lessons"] == [] and bare["context"] == score.SYSTEM


def test_claim_sentences_follow_the_prereg(monkeypatch):
    score = load(monkeypatch, "plug_r2_score")
    means = {"reader": {"pick": 0.8, "silence": 0.9}, "floor_plain": {"pick": 0.1}}
    win = {"decision": "better", "mean_gain": 0.7, "ci95_low": 0.6, "ci95_high": 0.8}
    tie = {"decision": "tie", "mean_gain": 0.02, "ci95_low": -0.05, "ci95_high": 0.09}
    assert score.claim(win, {"passes": True}, means).startswith(
        "picks the applicable lesson in 0.80"
    )
    assert score.claim(win, {"passes": False}, means) == "picks more and fails the abstention gate"
    assert score.claim(tie, {"passes": True}, means).startswith("the trained reader did not")


def test_check_refuses_any_input_whose_hash_differs_from_its_pin(monkeypatch):
    score = load(monkeypatch, "plug_r2_score")
    assert set(score.PINNED) == {"pool_index_sha256", "habit_rows_sha256", "aidev_lessons_sha256"}
    score.verify_pins(dict(score.PINNED))
    for name in score.PINNED:
        with pytest.raises(score.InputHashMismatchError, match=name):
            score.verify_pins({**score.PINNED, name: "0" * 64})


def test_seed_mean_averages_each_repos_rates_over_seeds(monkeypatch):
    select = load(monkeypatch, "plug_r2_select")
    seeds = [
        {"r": cell(0.3, silence=0.9)},
        {"r": cell(0.6, silence=0.6)},
        {"r": cell(0.9, silence=0.9)},
    ]
    found = select.seed_mean(seeds)
    assert found["r"]["pick"] == pytest.approx(0.6) and found["r"]["silence"] == pytest.approx(0.8)
    assert select.SEEDS == (0, 1, 2)
