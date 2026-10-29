"""AIDev review-flag labels on hand-written patches: hunk parsing, tracking, anchoring, order."""

import importlib.util
import sys
from pathlib import Path

import pytest

AIDEV = Path(__file__).resolve().parents[2] / "scripts" / "aidev"


@pytest.fixture(autouse=True)
def forget_aidev_modules():
    """Drop only the scripts/aidev modules a test loaded; shared libraries such as duckdb stay."""
    yield
    for name, module in list(sys.modules.items()):
        if Path(getattr(module, "__file__", None) or "/").parent == AIDEV:
            del sys.modules[name]


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(AIDEV))
    spec = importlib.util.spec_from_file_location(name, AIDEV / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# A file of ten lines; commit 0 adds two lines after line 3 inside `def parse(`.
ADD_TWO = "@@ -3,2 +3,4 @@ def parse(text):\n a\n+new1\n+new2\n b\n"
# Commit 1 edits an unrelated earlier line: inserts one line at the top, shifting everything.
INSERT_TOP = "@@ -1,1 +1,2 @@\n+header\n first\n"
# Commit 2 rewrites the line now at 5 (was new1 at 4 before the shift).
REWRITE_5 = "@@ -5,1 +5,1 @@\n-new1\n+fixed\n"
# A review hunk whose last line is new line 4 of the file at commit 0.
REVIEW_ON_4 = "@@ -1,3 +1,5 @@\n a\n b\n x\n+new1"


def test_parse_patch_numbers_both_sides(monkeypatch):
    hunks = load(monkeypatch, "hunks")
    (hunk,) = hunks.parse_patch(ADD_TWO)
    assert hunk.added == (4, 5)
    assert hunk.removed == ()
    assert hunk.inserted_before == (4, 4)
    assert hunks.section_name(hunk.section) == "parse"


def test_parse_patch_refuses_text_outside_a_hunk(monkeypatch):
    hunks = load(monkeypatch, "hunks")
    with pytest.raises(hunks.PatchError):
        hunks.parse_patch("+orphan line\n")


def test_file_change_shifts_and_touches(monkeypatch):
    hunks = load(monkeypatch, "hunks")
    top = hunks.FileChange.of(hunks.parse_patch(INSERT_TOP))
    assert not top.touches((4, 5))
    assert top.shift((4, 5)) == (5, 6)
    rewrite = hunks.FileChange.of(hunks.parse_patch(REWRITE_5))
    assert rewrite.touches((5, 6))
    inside = hunks.FileChange.of(hunks.parse_patch("@@ -5,2 +5,3 @@\n x\n+between\n y\n"))
    assert inside.touches((5, 6))
    after = hunks.FileChange.of(hunks.parse_patch("@@ -6,1 +6,2 @@\n y\n+after\n"))
    assert not after.touches((5, 6))


def test_anchor_line_is_the_last_new_side_line(monkeypatch):
    hunks = load(monkeypatch, "hunks")
    assert hunks.anchor_line(REVIEW_ON_4) == 4
    assert hunks.anchor_line("@@ -1,2 +1,1 @@\n a\n-gone") is None
    with pytest.raises(hunks.PatchError):
        hunks.anchor_line("no header")


def commits_of(flags, hunks, *patches):
    """One commit per patch, all on mod.py; None stands for a commit with no file rows."""
    made = []
    for i, patch in enumerate(patches):
        if patch is None:
            made.append(flags.Commit(f"s{i}", None))
            continue
        state = flags.FileState("modified", tuple(hunks.parse_patch(patch)))
        made.append(flags.Commit(f"s{i}", {"mod.py": state}))
    return made


def test_flagged_hunk_is_changed_after_tracking_through_a_shift(monkeypatch):
    hunks, flags = load(monkeypatch, "hunks"), load(monkeypatch, "flags")
    commits = commits_of(flags, hunks, ADD_TWO, INSERT_TOP, REWRITE_5)
    comment = flags.Comment(7, "s0", "mod.py", 4, human=True)
    labels = flags.label_pr(commits, [comment])
    (flagged,) = [u for u in labels.units if u.flag() is flags.Flag.HUMAN]
    assert flagged.commit_index == 0
    assert flagged.changed_at == 2
    assert flagged.outcome_after(flagged.human_at, labels.last_index) is flags.Outcome.CHANGED
    assert labels.anchoring["anchored"] == 1
    assert labels.first_review == 0


def test_unflagged_hunk_that_survives_and_last_commit_is_censored(monkeypatch):
    hunks, flags = load(monkeypatch, "hunks"), load(monkeypatch, "flags")
    commits = commits_of(flags, hunks, ADD_TWO, INSERT_TOP)
    label = flags.label_pr(commits, [])
    first, top = sorted(label.units, key=lambda unit: unit.commit_index)
    assert first.outcome_after(0, label.last_index) is flags.Outcome.SURVIVED
    assert top.outcome_after(1, label.last_index) is flags.Outcome.CENSORED
    assert first.flag() is flags.Flag.NONE


def test_commit_without_file_rows_makes_the_fate_unknown_not_survived(monkeypatch):
    hunks, flags = load(monkeypatch, "hunks"), load(monkeypatch, "flags")
    commits = commits_of(flags, hunks, ADD_TWO, None, INSERT_TOP)
    (unit, *_) = flags.label_pr(commits, []).units
    assert unit.outcome_after(0, 2) is flags.Outcome.UNKNOWN


def test_comments_that_cannot_anchor_are_counted_by_reason(monkeypatch):
    hunks, flags = load(monkeypatch, "hunks"), load(monkeypatch, "flags")
    commits = commits_of(flags, hunks, ADD_TWO)
    comments = [
        flags.Comment(1, "gone", "mod.py", 4, human=True),
        flags.Comment(2, "s0", "mod.py", None, human=True),
        flags.Comment(3, "s0", "mod.py", 9, human=False),
    ]
    label = flags.label_pr(commits, comments)
    assert label.anchoring == {"commit_not_in_pr": 1, "old_side": 1, "line_not_added_in_pr": 1}
    assert all(u.flag() is flags.Flag.NONE for u in label.units)


def test_order_votes_count_agreement_and_disagreement(monkeypatch):
    order = load(monkeypatch, "order")
    facts = [
        order.CommitFacts("a", {"x.py": "added"}, opens_with_plan=True),
        order.CommitFacts("b", {"x.py": "modified"}, opens_with_plan=False),
        order.CommitFacts("c", {"y.py": "modified"}, opens_with_plan=False),
        order.CommitFacts("d", {"y.py": "added"}, opens_with_plan=False),
    ]
    votes = order.order_votes(facts, [("b", "a"), ("a", "c"), ("zz", "a")])
    assert votes == {
        "added_before_modified_agree": 1,
        "added_before_modified_disagree": 1,
        "head_not_before_original_agree": 1,
        "head_not_before_original_disagree": 1,
        "plan_first_agree": 1,
    }
