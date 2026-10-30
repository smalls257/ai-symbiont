"""Plug round 4 continuous training: labels, rows, nights and repeat counting, hand-written."""

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


@pytest.fixture
def cont(monkeypatch):
    return load(monkeypatch, "plug_r4_cont")


def row(cont, answer):
    return {
        "messages": [{"role": "system"}, {"role": "user"}, {"role": "assistant", "content": answer}]
    }


@pytest.mark.parametrize(
    "reply, want", [("Yes.", "yes"), (" no ", "no"), ("YES, it applies", "yes")]
)
def test_labels_parse(cont, reply, want):
    assert cont.parsed_label(reply) == want


@pytest.mark.parametrize("reply", ["maybe", "", "It depends"])
def test_an_unreadable_label_raises_never_reads_as_no(cont, reply):
    with pytest.raises(cont.UnparsableLabelError):
        cont.parsed_label(reply)


def test_nights_are_contiguous_groups_capped_at_ten(cont):
    tasks = [f"o__r-{n}" for n in range(1, 24)]
    nights = cont.night_of(tasks)
    assert nights[tasks[0]] == 1 and nights[tasks[-1]] == 10
    assert [nights[t] for t in tasks] == sorted(nights[t] for t in tasks)


def test_few_tasks_get_one_night_each(cont):
    assert cont.night_of(["o__r-1", "o__r-2"]) == {"o__r-1": 1, "o__r-2": 2}


def test_balanced_rows_have_equal_yes_and_no(cont):
    rows = [row(cont, "yes")] * 3 + [row(cont, "no")] * 9
    kept = cont.balanced(rows)
    assert sum(r["messages"][2]["content"] == "yes" for r in kept) == 3 and len(kept) == 6


def test_replay_makes_up_the_requested_share(cont):
    mixed = cont.with_replay([row(cont, "yes")] * 30, [row(cont, "no")] * 100, 0.25)
    assert len(mixed) == 40 and sum(r["messages"][2]["content"] == "no" for r in mixed) == 10


def test_a_judge_miss_or_wrong_speaking_counts_twice(cont):
    pairs = [
        {"pair_id": "a", "situation": "s", "lesson_text": "t"},
        {"pair_id": "b", "situation": "s", "lesson_text": "t"},
        {"pair_id": "c", "situation": "s", "lesson_text": "t"},
    ]
    labels = {"a": "yes", "b": "no", "c": "yes"}
    scores = {"a": 0.2, "b": 0.999, "c": 0.999}  # silent on a yes, spoke on a no, right on a yes
    assert len(cont.labeled_rows(pairs, labels, scores)) == 2 + 2 + 1


def test_an_unlabeled_pair_gives_no_row(cont):
    pairs = [{"pair_id": "a", "situation": "s", "lesson_text": "t"}]
    assert cont.labeled_rows(pairs, {}, {"a": 0.5}) == []


@pytest.fixture
def repeats(monkeypatch):
    return load(monkeypatch, "plug_r4_repeats")


class Rec:
    def __init__(self, position, command, code, raw):
        self.kind = importlib_kind()
        self.exit_code, self.command, self.raw, self.step = code, command, raw, position


def importlib_kind():
    from symbiont.records.schema import Kind

    return Kind.COMMAND


def test_a_within_session_repeat_is_found_and_marked_fixed(repeats):
    class Norm:
        @staticmethod
        def normalize_error_line(line):
            return line

    boom = "KeyError: x"
    session = [
        Rec(0, "pytest a", 1, boom),
        Rec(1, "pytest a", 1, boom),
        Rec(2, "pytest a -x", 0, "ok"),
    ]
    failures = repeats.session_failures(session, Norm)
    assert [k for _, k, _ in failures] == [boom, boom]
    assert repeats.within_session(session, failures) == [(boom, True)]


def test_a_single_failure_is_not_a_repeat(repeats):
    class Norm:
        @staticmethod
        def normalize_error_line(line):
            return line

    session = [Rec(0, "pytest a", 1, "KeyError: x")]
    assert repeats.within_session(session, repeats.session_failures(session, Norm)) == []


def test_habit_rows_make_up_the_share_in_every_repository(cont, tmp_path):
    import json

    folder = tmp_path / "habits10" / "o__r"
    folder.mkdir(parents=True)
    rows = [row(cont, "yes")] * 85
    (folder / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    habit = {"messages": [{"role": "user"}, {"role": "assistant", "content": "habit"}]}
    assert cont.add_habits(tmp_path, [habit], 0.15) == 1
    out = [json.loads(x) for x in (folder / "train.jsonl").read_text().splitlines()]
    assert len(out) == 100 and sum(r["messages"][-1]["content"] == "habit" for r in out) == 15


def test_cutoffs_take_the_earliest_scored_recurrence_per_repository(monkeypatch):
    load(monkeypatch, "plug_r4_primary")
    module = load(monkeypatch, "plug_r4_scored_nightly")

    class Item:
        def __init__(self, item_id, applies):
            self.item_id, self.applies = item_id, applies

    items = [
        Item("o__r:o__r-9:aa-pick", 1),
        Item("o__r:o__r-3:bb-pick", 1),
        Item("o__r:o__r-1:cc-silence", None),
    ]
    repo_of = {i.item_id: "o/r" for i in items}
    dates = {"o__r-9": "2024-03-01", "o__r-3": "2024-02-01", "o__r-1": "2024-01-01"}
    assert module.cutoffs(items, repo_of, dates) == {"o/r": ("2024-02-01", "o__r-3")}


def test_only_tasks_strictly_before_the_cutoff_are_known(monkeypatch):
    primary = load(monkeypatch, "plug_r4_primary")
    module = load(monkeypatch, "plug_r4_scored_nightly")
    tasks = [primary.TaskEvents(f"o__r-{n}", f"2024-0{n}-01", (), ()) for n in (1, 2, 3)]
    kept = module.before(tasks, ("2024-02-01", "o__r-2"))
    assert [t.task for t in kept] == ["o__r-1"]


def test_a_repository_without_scores_is_refused_unless_it_is_idle(monkeypatch, tmp_path):
    load(monkeypatch, "plug_r4_primary")
    load(monkeypatch, "plug_r4_scored")
    load(monkeypatch, "plug_r4_general_arm")
    arm = load(monkeypatch, "plug_r4_nightly_arm")
    repo_of = {"q1": "o/r"}
    with pytest.raises(arm.PinMismatchError):
        arm.arm_scores(tmp_path, "1", set(), {}, repo_of)
    assert arm.arm_scores(tmp_path, "1", {"o/r"}, {"q1": 0.4}, repo_of) == {"q1": 0.4}


def test_an_adapter_set_with_no_adapters_cannot_be_pinned(monkeypatch, tmp_path):
    load(monkeypatch, "plug_r4_primary")
    load(monkeypatch, "plug_r4_scored")
    load(monkeypatch, "plug_r4_general_arm")
    arm = load(monkeypatch, "plug_r4_nightly_arm")
    with pytest.raises(arm.PinMismatchError):
        arm.adapters_hash(tmp_path, "1")


@pytest.fixture
def nightly(monkeypatch):
    load(monkeypatch, "plug_r4_primary")
    load(monkeypatch, "plug_r4_scored")
    load(monkeypatch, "plug_r4_general_arm")
    return load(monkeypatch, "plug_r4_nightly_arm")


def test_better_needs_the_interval_and_a_wrong_pick_bound_of_five_percent(nightly):
    base = {"reading": "better", "wrong_bound_rule": 0.04}
    assert nightly.nightly_reading(base)["reading"] == "better"
    assert nightly.nightly_reading({**base, "wrong_bound_rule": 0.06})["reading"] == "no claim"
    assert (
        nightly.nightly_reading({"reading": "tie", "wrong_bound_rule": 0.01})["reading"]
        == "no claim"
    )


def test_an_amendment_may_add_only_the_adapter_hashes_idle_list_and_date(nightly, tmp_path):
    adapters = tmp_path / "a" / "habits10-o__r"
    adapters.mkdir(parents=True)
    (adapters / "adapter_model.safetensors").write_text("w")
    idle = tmp_path / "idle.json"
    idle.write_text("[]")
    pins = nightly.amendment_pins(tmp_path / "a", idle, "2026-10-30")
    assert set(pins) == nightly.AMENDMENT_KEYS


def test_freeze_pins_carry_only_selection_and_strength(nightly, tmp_path):
    selection = tmp_path / "s.json"
    selection.write_text("{}")
    assert set(nightly.freeze_pins(selection, "1")) == {"nightly_selection", "nightly_scale"}


def test_a_general_arm_without_its_scores_is_refused(monkeypatch, tmp_path):
    load(monkeypatch, "plug_r4_primary")
    load(monkeypatch, "plug_r4_scored")
    general = load(monkeypatch, "plug_r4_general_arm")
    (tmp_path / "q.jsonl").write_text('{"question_id": "a::1"}\n')
    with pytest.raises(general.PinMismatchError):
        general.read_general(tmp_path, tmp_path / "q.jsonl")
    (tmp_path / "primary-general.jsonl").write_text('{"question_id": "other", "p_yes": 0.5}\n')
    with pytest.raises(general.PinMismatchError):
        general.read_general(tmp_path, tmp_path / "q.jsonl")
