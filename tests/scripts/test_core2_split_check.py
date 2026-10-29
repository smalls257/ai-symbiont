"""Core D2 split check: commit-date order and the duplicate/revert rule."""

import importlib.util
from pathlib import Path

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"
spec = importlib.util.spec_from_file_location("core2_split_check", ROUTEB / "core2_split_check.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

ADD_FOO = "--- a/x\n+++ b/x\n+foo = 1\n+bar = 2\n"


def test_patch_lines_split_added_and_removed():
    assert module.patch_lines("--- a/x\n+++ b/x\n+a\n-b\n+  \n") == ({"a"}, {"b"})


def test_duplicate_share_counts_lines_an_earlier_patch_added_or_removed():
    redo = "--- a/x\n+++ b/x\n+foo = 1\n+new = 3\n"
    assert module.duplicate_share(redo, [ADD_FOO]) == 0.5
    revert = "--- a/x\n+++ b/x\n+foo = 1\n+bar = 2\n"
    assert module.duplicate_share(revert, [ADD_FOO]) == 1.0


def test_later_task_must_be_strictly_after_every_earlier_base(monkeypatch):
    dates = {"e1": "2021-01-01T00:00:00+00:00", "e2": "2021-03-01T00:00:00+00:00",
             "l1": "2021-02-01T00:00:00+00:00", "l2": "2021-04-01T00:00:00+00:00"}  # fmt: skip
    monkeypatch.setattr(module, "commit_date", lambda clone, sha: dates[sha])
    row = lambda i, patch: {"instance_id": i, "base_commit": i, "patch": patch}  # noqa: E731
    result = module.check_repo(
        [row("e1", ADD_FOO), row("e2", ADD_FOO)],
        [row("l1", "+z\n"), row("l2", "+z\n")],
        Path("."),
    )
    assert result["keep_ids"] == ["l2"]
    assert result["drop_base_not_after"] == 1
