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
