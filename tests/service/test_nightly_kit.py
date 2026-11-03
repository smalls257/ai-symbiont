"""The judge kit: a missing piece raises and names itself, never a different judge."""

import json

import pytest

from nightly_support import chat, general_rows
from symbiont.service.nightly_kit import JudgeKitError, open_kit, read_rows

pytestmark = pytest.mark.periphery


def make_kit(root, base=True, general=True, habits=True):
    if base:
        (root / "base").mkdir(parents=True)
        (root / "base" / "config.json").write_text("{}")
    if general:
        write_rows(root / "general-rows.jsonl", general_rows(3))
    if habits:
        write_rows(root / "habits.jsonl", [chat("h", "q", "a")])


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_a_complete_kit_opens(tmp_path):
    make_kit(tmp_path)
    kit = open_kit(tmp_path)
    assert kit.base == tmp_path / "base"
    assert len(read_rows(kit.general_rows)) == 3


@pytest.mark.parametrize(
    ("missing", "named"),
    [("base", "base/config.json"), ("general", "general-rows.jsonl"), ("habits", "habits.jsonl")],
)
def test_every_missing_piece_is_named(tmp_path, missing, named):
    make_kit(tmp_path, **{missing: False})
    with pytest.raises(JudgeKitError, match=named):
        open_kit(tmp_path)


def test_a_bad_row_is_reported_with_file_and_line(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(chat("s", "u", "a")) + "\n{not json}\n")
    with pytest.raises(JudgeKitError, match=r"rows.jsonl:2"):
        read_rows(path)


def test_a_row_without_three_messages_and_an_empty_file_both_raise(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps({"messages": [{"role": "user", "content": "x"}]}) + "\n")
    with pytest.raises(JudgeKitError, match=r":1"):
        read_rows(path)
    path.write_text("\n")
    with pytest.raises(JudgeKitError, match="no rows"):
        read_rows(path)
